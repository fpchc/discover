"""阶段执行器注册表（react-runtime-v2-architecture §9.2/§21）。

单一动机：按 PhaseExecutorType 把「一个阶段怎么做」分派到具体执行器。
平台经 executors 注册表解释阶段；具体阶段名称与业务含义由 Skill Pack 声明。
react 执行器复用 BoundedReAct 子图；render 执行器关闭工具，仅生成最终正文。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.capabilities.llm.models import ChatMessage, ChatRequest
from app.capabilities.llm.stream_parser import TextChunk, ThinkingChunk, UsageChunk
from app.harness.events.run_events import LLMUsageUpdated
from app.harness.models import (
    BudgetUsage,
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
)
from app.harness.react.executor import (
    BoundedReActExecutor,
    EventSinkPort,
    LLMRunnerPort,
    ReactGraphState,
)
from app.harness.workflow.definition import PhaseDefinition, PhaseExecutorType


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
        from app.harness.graph import build_react_subgraph

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


class RenderPhaseExecutor:
    """render 阶段：关闭普通工具，基于上游采集上下文生成最终正文。

    LLM 在这里只产出正文；阶段进入与退出由 WorkflowRunner 确定性控制，
    不依赖模型调用 submit_final_answer / complete_phase。
    """

    def __init__(
        self,
        llm: LLMRunnerPort,
        *,
        events: EventSinkPort | None = None,
        display_text: Callable[[str], None] | None = None,
        display_thinking: Callable[[str], None] | None = None,
    ) -> None:
        self._llm = llm
        self._events = events
        self._display_text = display_text
        self._display_thinking = display_thinking

    async def execute(
        self, definition: PhaseDefinition, request: PhaseExecutionRequest
    ) -> PhaseExecutionOutcome:
        del definition
        system_prompt = request.system_prompt or (
            "你是最终文案生成器。基于已采集信息输出最终正文，不要调用工具。"
        )
        user_parts: list[str] = []
        user_goal = request.phase_input.get("user_goal")
        if user_goal:
            user_parts.append(f"用户目标：{user_goal}")
        if request.context_summary:
            user_parts.append(f"已采集信息：\n{request.context_summary}")
        user_parts.append(f"任务：{request.phase_goal}")
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content="\n\n".join(user_parts)),
        ]
        usage = {"input": 0, "output": 0, "total": 0, "cached_read": 0, "cached_write": 0}
        text_parts: list[str] = []
        async for chunk in self._llm.stream(
            request=ChatRequest(
                messages=messages,
                thinking=request.thinking_enabled,
                thinking_budget=request.thinking_budget,
            )
        ):
            if isinstance(chunk, TextChunk):
                text_parts.append(chunk.text)
                if self._display_text is not None:
                    self._display_text(chunk.text)
            elif isinstance(chunk, ThinkingChunk):
                if self._display_thinking is not None:
                    self._display_thinking(chunk.text)
            elif isinstance(chunk, UsageChunk):
                usage = _accumulate_usage(usage, chunk)
        if self._events is not None:
            await self._events.emit(
                LLMUsageUpdated(
                    run_id=request.run_id,
                    phase_id=request.phase_instance_id,
                    call_index=0,
                    usage=usage,
                )
            )
        return PhaseExecutionOutcome(
            outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
            answer="".join(text_parts),
            usage_snapshot=BudgetUsage(
                total_tokens=usage["total"],
                input_tokens=usage["input"],
            ),
            reason_code="render_completed",
        )


def _accumulate_usage(acc: dict[str, int], chunk: UsageChunk) -> dict[str, int]:
    """累加 UsageChunk 到 5 键用量形状。"""
    return {
        "input": acc["input"] + chunk.input_tokens,
        "output": acc["output"] + chunk.output_tokens,
        "total": acc["total"] + chunk.total_tokens,
        "cached_read": acc["cached_read"] + chunk.cached_read_tokens,
        "cached_write": acc["cached_write"] + chunk.cached_write_tokens,
    }


class PhaseExecutorRegistry:
    """按阶段执行器类型分派（策略注册表，OCP）。"""

    def __init__(self, executors: dict[PhaseExecutorType, PhaseExecutor]) -> None:
        self._executors = executors

    def resolve(self, executor_type: PhaseExecutorType) -> PhaseExecutor:
        executor = self._executors.get(executor_type)
        if executor is None:
            raise KeyError(f"未注册的阶段执行器：{executor_type}")
        return executor
