"""Workflow 编译器（react-runtime-v2-architecture §9）。

单一动机：把 WorkflowDefinition 编译为可执行的多阶段流程。阶段内控制由
Bounded ReAct 子图（LangGraph，§10）承载；阶段间推进由本模块的确定性编排
驱动（§9.3/§23.6），不依赖提示词自然语言。

闭环（§9.4）：PhaseExecutor → PhaseExecutionOutcome → Contract 决策 →
complete / repair / degrade / fail。首期聚焦阶段顺序推进与输出固化；
Contract 接入契约上下文由 W5 体系复用。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.harness.contracts.executor import ContractContext, GateRunnerPort, ScriptGateExecutor
from app.harness.contracts.models import ContractDefinition, ContractType, ContractVerdict
from app.harness.models import (
    BudgetState,
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
    PhaseOutput,
)
from app.harness.workflow.definition import PhaseDefinition, WorkflowDefinition
from app.harness.workflow.executors import PhaseExecutorRegistry
from app.llm.models import ChatMessage


class PhaseRun(BaseModel):
    """单阶段执行记录（跨边界 DTO）。"""

    phase: PhaseDefinition
    outcome: PhaseExecutionOutcome
    output: PhaseOutput | None = None


class WorkflowRunResult(BaseModel):
    """多阶段执行结果。"""

    phases: list[PhaseRun] = Field(default_factory=list)
    completed_phase_ids: list[str] = Field(default_factory=list)
    final_outcome: PhaseExecutionOutcome | None = None
    reason_code: str = ""


class WorkflowRunner:
    """把 WorkflowDefinition 编排为顺序阶段执行（§9.1/§9.2 单阶段与多阶段共用）。"""

    def __init__(
        self,
        *,
        executors: PhaseExecutorRegistry,
        max_repair_attempts: int = 1,
        gate_runner: GateRunnerPort | None = None,
    ) -> None:
        self._executors = executors
        self._max_repair_attempts = max_repair_attempts
        self._gate_runner = gate_runner

    async def run(
        self,
        definition: WorkflowDefinition,
        *,
        run_id: str,
        phase_input: dict[str, object],
        budget: BudgetState,
        allowed_tools: list[str],
        context_summary: str = "",
        context_messages: list[ChatMessage] | None = None,
        system_prompt: str = "",
        thinking_enabled: bool = True,
        thinking_budget: int | None = None,
        tool_message_max_chars: int = 2000,
    ) -> WorkflowRunResult:
        """顺序执行所有阶段，返回各阶段结果与最终 outcome。

        - 正常完成（CANDIDATE_COMPLETED）→ 固化 PhaseOutput 并进入下一阶段；
        - 非完成但声明 fallback_phase → 确定性跳到 fallback 阶段，并把当前
          outcome.context_payload 作为下一阶段的 context_summary；
        - 其他非完成结果 → 终止后续阶段。
        """
        result = WorkflowRunResult()
        outputs: dict[str, PhaseOutput] = {}
        index = 0
        fallback_context = ""
        final_phase: PhaseDefinition | None = None
        final_request: PhaseExecutionRequest | None = None
        while index < len(definition.phases):
            phase = definition.phases[index]
            bound = dict(phase_input)
            bound.update(self._apply_bindings(phase, outputs))
            phase_tools = allowed_tools if phase.inherit_tools else phase.allowed_tools
            request = PhaseExecutionRequest(
                run_id=run_id,
                phase_instance_id=phase.phase_id,
                phase_goal=phase.goal,
                system_prompt=system_prompt,
                phase_input=bound,
                context_summary=fallback_context or context_summary,
                context_messages=list(context_messages or []),
                allowed_tools=phase_tools,
                thinking_enabled=thinking_enabled,
                thinking_budget=thinking_budget,
                tool_message_max_chars=tool_message_max_chars,
                budget=budget,
                contract_refs=phase.contract_refs,
            )
            outcome = await self._executors.resolve(phase.executor_type).execute(phase, request)

            if outcome.outcome_type == PhaseExecutionOutcomeType.CANDIDATE_COMPLETED:
                phase_output = self._to_output(phase, outcome)
                outputs[phase.phase_id] = phase_output
                result.completed_phase_ids.append(phase.phase_id)
                result.phases.append(PhaseRun(phase=phase, outcome=outcome, output=phase_output))
                index += 1
                fallback_context = ""
                continue

            fallback_phase = phase.fallback_phase
            fallback_index = self._find_phase_index(definition, fallback_phase)
            if fallback_index is not None and fallback_index > index:
                result.phases.append(PhaseRun(phase=phase, outcome=outcome))
                index = fallback_index
                fallback_context = outcome.context_payload
                continue

            result.phases.append(PhaseRun(phase=phase, outcome=outcome))
            result.final_outcome = outcome
            result.reason_code = outcome.reason_code or outcome.outcome_type.value
            final_phase = phase
            final_request = request
            break
        if final_phase is not None and final_request is not None:
            result = await self._enforce_output_contracts(
                definition,
                result,
                final_phase=final_phase,
                final_request=final_request,
            )
        return result

    def _apply_bindings(
        self, phase: PhaseDefinition, outputs: dict[str, PhaseOutput]
    ) -> dict[str, object]:
        """按 input_bindings 只读绑定上游 PhaseOutput 字段（§9.4 输入绑定）。"""
        bound: dict[str, object] = {}
        for upstream_path, local_field in phase.input_bindings.items():
            upstream_phase_id, _, field = upstream_path.partition(".")
            upstream = outputs.get(upstream_phase_id)
            if upstream is None:
                continue
            if field:
                bound[local_field] = upstream.data.get(field)
            else:
                bound[local_field] = upstream.data
        return bound

    @staticmethod
    def _find_phase_index(definition: WorkflowDefinition, phase_id: str | None) -> int | None:
        if phase_id is None:
            return None
        for index, phase in enumerate(definition.phases):
            if phase.phase_id == phase_id:
                return index
        return None

    def _to_output(self, phase: PhaseDefinition, outcome: PhaseExecutionOutcome) -> PhaseOutput:
        """固化候选输出为不可变、带版本的 PhaseOutput（§9.4）。"""
        return PhaseOutput(
            phase_id=phase.phase_id,
            data=outcome.candidate_output or {},
            evidence_refs=list(outcome.action_ids),
            limitations=list(outcome.limitations),
        )

    async def _enforce_output_contracts(
        self,
        workflow: WorkflowDefinition,
        result: WorkflowRunResult,
        *,
        final_phase: PhaseDefinition,
        final_request: PhaseExecutionRequest,
    ) -> WorkflowRunResult:
        """render 等收尾阶段产出后，确定性执行输出门禁并做有界修复（§9.4）。"""
        if not workflow.output_contract_refs or self._gate_runner is None:
            return result
        outcome = result.final_outcome
        if outcome is None or outcome.outcome_type != PhaseExecutionOutcomeType.FINAL_PROPOSED:
            return result
        executor = ScriptGateExecutor(self._gate_runner)
        data = self._contract_data(final_request, outcome.answer)
        for attempt in range(self._max_repair_attempts + 1):
            failures = await self._run_output_contracts(
                workflow.output_contract_refs, executor, data
            )
            if not failures:
                result.reason_code = outcome.reason_code or "output_contract_passed"
                return result
            if attempt >= self._max_repair_attempts:
                result.reason_code = "output_contract_failed:" + ",".join(
                    workflow.output_contract_refs
                )
                return result
            repair_goal = (
                f"{final_request.phase_goal}\n\n"
                "上一版未通过输出门禁，请按以下问题修复后重新输出：\n"
                f"{_remediation_text(failures)}"
            )
            repair_request = final_request.model_copy(update={"phase_goal": repair_goal})
            outcome = await self._executors.resolve(final_phase.executor_type).execute(
                final_phase, repair_request
            )
            data = self._contract_data(final_request, outcome.answer)
            result.final_outcome = outcome
            result.reason_code = outcome.reason_code or "render_repaired"
        return result

    async def _run_output_contracts(
        self,
        refs: list[str],
        executor: ScriptGateExecutor,
        data: dict[str, object],
    ) -> list[str]:
        """逐条执行输出门禁，返回全部失败项（空 = 全部通过）。"""
        failures: list[str] = []
        for ref in refs:
            definition = ContractDefinition(
                contract_id=ref,
                contract_type=ContractType.QUALITY,
                retryable=True,
            )
            contract_result = await executor.execute(definition, ContractContext(data=data))
            if contract_result.verdict == ContractVerdict.FAIL:
                failures.extend(contract_result.failures or [contract_result.remediation])
        return failures

    @staticmethod
    def _contract_data(request: PhaseExecutionRequest, answer: str) -> dict[str, object]:
        """输出契约上下文：最终正文 + 本阶段绑定的结构化输入（如 report/card_data）。"""
        data = dict(request.phase_input)
        data["answer"] = answer
        return data


def _remediation_text(failures: list[str]) -> str:
    """把门禁失败项整理成可回填 render 提示词的修复说明。"""
    parts: list[str] = []
    for item in failures:
        text = item.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                errors = payload.get("errors")
                if isinstance(errors, list) and errors:
                    parts.extend(str(error) for error in errors)
                    continue
        except (json.JSONDecodeError, TypeError):
            pass
        parts.append(text)
    return "\n".join(f"- {part}" for part in parts) or "- 门禁未通过"
