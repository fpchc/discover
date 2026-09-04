"""Workflow 编译器（react-runtime-v2-architecture §9）。

单一动机：把 WorkflowDefinition 编译为可执行的多阶段流程。阶段内控制由
Bounded ReAct 子图（LangGraph，§10）承载；阶段间推进由本模块的确定性编排
驱动（§9.3/§23.6），不依赖提示词自然语言。

闭环（§9.4）：PhaseExecutor → PhaseExecutionOutcome → Contract 决策 →
complete / repair / degrade / fail。首期聚焦阶段顺序推进与输出固化；
Contract 接入契约上下文由 W5 体系复用。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.runtime.models import (
    BudgetState,
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
    PhaseOutput,
)
from app.runtime.workflow.definition import PhaseDefinition, WorkflowDefinition
from app.runtime.workflow.executors import PhaseExecutorRegistry


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
    ) -> None:
        self._executors = executors
        self._max_repair_attempts = max_repair_attempts

    async def run(
        self,
        definition: WorkflowDefinition,
        *,
        run_id: str,
        phase_input: dict[str, object],
        budget: BudgetState,
        allowed_tools: list[str],
        context_summary: str = "",
    ) -> WorkflowRunResult:
        """顺序执行所有阶段，返回各阶段结果与最终 outcome。"""
        result = WorkflowRunResult()
        outputs: dict[str, PhaseOutput] = {}
        for phase in definition.phases:
            bound = self._apply_bindings(phase, outputs)
            request = PhaseExecutionRequest(
                run_id=run_id,
                phase_instance_id=phase.phase_id,
                phase_goal=phase.goal,
                phase_input=bound,
                context_summary=context_summary,
                allowed_tools=phase.allowed_tools or allowed_tools,
                budget=budget,
                contract_refs=phase.contract_refs,
            )
            outcome = await self._executors.resolve(phase.executor_type).execute(phase, request)
            if outcome.outcome_type == PhaseExecutionOutcomeType.CANDIDATE_COMPLETED:
                phase_output = self._to_output(phase, outcome)
                outputs[phase.phase_id] = phase_output
                result.completed_phase_ids.append(phase.phase_id)
                result.phases.append(PhaseRun(phase=phase, outcome=outcome, output=phase_output))
                continue
            # 非完成结果（PARTIAL / FAILED / FINAL / INPUT_REQUIRED）：终止后续阶段
            result.phases.append(PhaseRun(phase=phase, outcome=outcome))
            result.final_outcome = outcome
            result.reason_code = outcome.reason_code or outcome.outcome_type.value
            break
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

    def _to_output(self, phase: PhaseDefinition, outcome: PhaseExecutionOutcome) -> PhaseOutput:
        """固化候选输出为不可变、带版本的 PhaseOutput（§9.4）。"""
        return PhaseOutput(
            phase_id=phase.phase_id,
            data=outcome.candidate_output or {},
            evidence_refs=list(outcome.action_ids),
            limitations=list(outcome.limitations),
        )
