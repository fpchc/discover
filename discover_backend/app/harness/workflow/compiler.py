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
from enum import StrEnum

from pydantic import BaseModel, Field

from app.harness.contracts.executor import ContractContext, GateRunnerPort, ScriptGateExecutor
from app.harness.contracts.models import (
    ContractDefinition,
    ContractResult,
    ContractType,
    ContractVerdict,
)
from app.harness.contracts.registry import decide_repair
from app.harness.contracts.structural import has_structural_contract, structural_failures
from app.harness.models import (
    BudgetState,
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
    PhaseOutput,
)
from app.harness.policy.models import PolicyDecisionType
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


class _SettleAction(StrEnum):
    """阶段转换决策（内部）。"""

    ADVANCE = "advance"
    DEGRADE = "degrade"
    TERMINATE = "terminate"


class _Settlement(BaseModel):
    """阶段转换结果（内部值对象）：动作 + 外层循环所需的下标/上下文/终态。"""

    action: _SettleAction
    next_index: int = 0
    fallback_context: str = ""
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
                output_schema=phase.output_schema,
            )
            outcome = await self._executors.resolve(phase.executor_type).execute(phase, request)

            if outcome.outcome_type == PhaseExecutionOutcomeType.CANDIDATE_COMPLETED:
                settlement = await self._settle_candidate(
                    definition,
                    phase,
                    request,
                    outcome,
                    index=index,
                    outputs=outputs,
                    result=result,
                )
                if settlement.action == _SettleAction.ADVANCE:
                    index += 1
                    fallback_context = ""
                    continue
                if settlement.action == _SettleAction.DEGRADE:
                    index = settlement.next_index
                    fallback_context = settlement.fallback_context
                    continue
                result.final_outcome = settlement.final_outcome
                result.reason_code = settlement.reason_code
                final_phase = phase
                final_request = request
                break

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

    async def _settle_candidate(
        self,
        definition: WorkflowDefinition,
        phase: PhaseDefinition,
        request: PhaseExecutionRequest,
        outcome: PhaseExecutionOutcome,
        *,
        index: int,
        outputs: dict[str, PhaseOutput],
        result: WorkflowRunResult,
    ) -> _Settlement:
        """CANDIDATE_COMPLETED 阶段转换点：结构契约闸门 + decide_repair 有界修复。

        - 无结构契约或通过 → 固化 PhaseOutput，推进下一阶段（ADVANCE）；
        - 失败且可重试 → 同阶段带修复说明重跑（受 max_repair_attempts 约束）；
        - 重试耗尽且有 fallback → 确定性降级跳转（DEGRADE）；
        - 无路可走 → 终止（TERMINATE），final_outcome 交下游 Verifier 兜底判定。
        """
        repair_attempts = 0
        while True:
            failures = (
                structural_failures(outcome.output_schema, outcome.candidate_output)
                if has_structural_contract(outcome.output_schema)
                else []
            )
            if not failures:
                phase_output = self._to_output(phase, outcome)
                outputs[phase.phase_id] = phase_output
                result.completed_phase_ids.append(phase.phase_id)
                result.phases.append(PhaseRun(phase=phase, outcome=outcome, output=phase_output))
                return _Settlement(action=_SettleAction.ADVANCE)

            decision = decide_repair(
                ContractResult(
                    contract_id=phase.phase_id,
                    contract_type=ContractType.STRUCTURAL,
                    verdict=ContractVerdict.FAIL,
                    failures=failures,
                    retryable=True,
                    fallback=phase.fallback_phase or "",
                ),
                repair_attempts=repair_attempts,
                max_repair_attempts=self._max_repair_attempts,
            )
            if decision.decision == PolicyDecisionType.RETRY:
                repair_attempts += 1
                request = request.model_copy(
                    update={
                        "phase_goal": self._repair_goal(phase.goal, failures),
                        "attempt": request.attempt + 1,
                    }
                )
                outcome = await self._executors.resolve(phase.executor_type).execute(phase, request)
                continue
            if decision.decision == PolicyDecisionType.DEGRADE:
                fallback_index = self._find_phase_index(definition, decision.fallback_phase)
                if fallback_index is not None and fallback_index > index:
                    result.phases.append(PhaseRun(phase=phase, outcome=outcome))
                    return _Settlement(
                        action=_SettleAction.DEGRADE,
                        next_index=fallback_index,
                        fallback_context=outcome.context_payload,
                    )
            result.phases.append(PhaseRun(phase=phase, outcome=outcome))
            return _Settlement(
                action=_SettleAction.TERMINATE,
                final_outcome=outcome,
                reason_code=f"contract_failed:{phase.phase_id}",
            )

    @staticmethod
    def _repair_goal(phase_goal: str, failures: list[str]) -> str:
        """契约失败 → 回填阶段目标的修复说明，供结构闸门与输出门禁共用。"""
        return (
            f"{phase_goal}\n\n"
            "上一版输出未通过契约校验，请按以下问题修复后重新输出：\n"
            f"{_remediation_text(failures)}"
        )

    async def _enforce_output_contracts(
        self,
        workflow: WorkflowDefinition,
        result: WorkflowRunResult,
        *,
        final_phase: PhaseDefinition,
        final_request: PhaseExecutionRequest,
    ) -> WorkflowRunResult:
        """render 等收尾阶段产出后，确定性执行输出门禁并做有界修复（§9.4）。

        与阶段转换结构闸门（_settle_candidate）共用 decide_repair 作为唯一
        FAIL→路径 决策源；本处无 fallback，重试耗尽即 TERMINATE。
        """
        if not workflow.output_contract_refs or self._gate_runner is None:
            return result
        outcome = result.final_outcome
        if outcome is None or outcome.outcome_type != PhaseExecutionOutcomeType.FINAL_PROPOSED:
            return result
        executor = ScriptGateExecutor(self._gate_runner)
        data = self._contract_data(final_request, outcome.answer)
        repair_attempts = 0
        while True:
            aggregate = await self._run_output_contracts(
                workflow.output_contract_refs, executor, data
            )
            if aggregate.verdict == ContractVerdict.PASS:
                result.reason_code = outcome.reason_code or "output_contract_passed"
                return result
            decision = decide_repair(
                aggregate,
                repair_attempts=repair_attempts,
                max_repair_attempts=self._max_repair_attempts,
            )
            if decision.decision != PolicyDecisionType.RETRY:
                result.reason_code = decision.reason_code
                return result
            repair_attempts += 1
            repair_request = final_request.model_copy(
                update={
                    "phase_goal": self._repair_goal(final_request.phase_goal, aggregate.failures)
                }
            )
            outcome = await self._executors.resolve(final_phase.executor_type).execute(
                final_phase, repair_request
            )
            data = self._contract_data(final_request, outcome.answer)
            result.final_outcome = outcome
        return result

    async def _run_output_contracts(
        self,
        refs: list[str],
        executor: ScriptGateExecutor,
        data: dict[str, object],
    ) -> ContractResult:
        """逐条执行输出门禁，聚合为单个 ContractResult（任一 gate 失败即 FAIL）。"""
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
        return ContractResult(
            contract_id=",".join(refs),
            contract_type=ContractType.QUALITY,
            verdict=ContractVerdict.FAIL if failures else ContractVerdict.PASS,
            failures=failures,
            retryable=True,
        )

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
