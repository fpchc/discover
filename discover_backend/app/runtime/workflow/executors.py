"""阶段执行器注册表（react-runtime-v2-architecture §9.2/§21）。

单一动机：按 PhaseExecutorType 把「一个阶段怎么做」分派到具体执行器。
平台经 executors 注册表解释阶段；具体阶段名称与业务含义由 Skill Pack 声明。
react 执行器复用 BoundedReAct 子图；其余执行器（script/tool/contract/transform/
render）为后续能力，注册后统一走同一 PhaseExecutor 契约。
"""

from __future__ import annotations

from typing import Protocol

from app.runtime.models import (
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
)
from app.runtime.react.executor import BoundedReActExecutor, ReactGraphState
from app.runtime.workflow.definition import PhaseDefinition, PhaseExecutorType


class PhaseExecutor(Protocol):
    """单阶段执行抽象：请求 → 结构化结果（§9.4 PhaseExecutionOutcome）。"""

    async def execute(
        self, definition: PhaseDefinition, request: PhaseExecutionRequest
    ) -> PhaseExecutionOutcome: ...


class ReactPhaseExecutor:
    """react 阶段：委托 BoundedReAct 子图执行（§10 拓扑）。"""

    def __init__(self, react: BoundedReActExecutor) -> None:
        self._react = react

    async def execute(
        self, definition: PhaseDefinition, request: PhaseExecutionRequest
    ) -> PhaseExecutionOutcome:
        del definition  # react 阶段目标由 PhaseExecutionRequest.phase_goal 承载
        from app.runtime.graph import build_react_subgraph

        graph = build_react_subgraph(self._react)
        initial = ReactGraphState(request=request, budget=request.budget)
        final = await graph.ainvoke(initial)
        state = ReactGraphState.model_validate(final)
        if state.outcome is None:
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.FAILED,
                reason_code=state.terminate_reason or "no_phase_outcome",
            )
        return state.outcome


class PhaseExecutorRegistry:
    """按阶段执行器类型分派（策略注册表，OCP）。"""

    def __init__(self, executors: dict[PhaseExecutorType, PhaseExecutor]) -> None:
        self._executors = executors

    def resolve(self, executor_type: PhaseExecutorType) -> PhaseExecutor:
        executor = self._executors.get(executor_type)
        if executor is None:
            raise KeyError(f"未注册的阶段执行器：{executor_type}")
        return executor
