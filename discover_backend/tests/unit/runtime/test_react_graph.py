"""Bounded ReAct 子图图级测试（W2-W3，§24 场景）。

Fake LLM 脚本化返回语义分片，跑通：正常完成、无限重复同一 Action、A/B 交替
无进展（预算终止）、重复 Action 但每次有新进展、预算硬边界确定性终止。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from app.capabilities.llm.models import ChatToolSpec, ToolFunction
from app.capabilities.llm.stream_parser import (
    SemanticChunk,
    ToolCall,
    ToolCallsChunk,
)
from app.capabilities.tools.broker import ToolCallRequest, ToolResult
from app.capabilities.tools.descriptor import ToolDescriptor, ToolSource
from app.runtime.events.run_events import RunEvent
from app.runtime.graph import build_react_subgraph
from app.runtime.models import (
    BudgetLimits,
    BudgetState,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
)
from app.runtime.react.executor import (
    BoundedReActExecutor,
    LLMRunnerPort,
    ReactGraphState,
    ToolRunnerPort,
)
from langgraph.graph.state import CompiledStateGraph


class _FakeLLM(LLMRunnerPort):
    """脚本化 LLM：按调用序号产出语义分片（Fake LLM，无网络）。"""

    def __init__(self, respond: Callable[[int], list[SemanticChunk]]) -> None:
        self._respond = respond
        self.calls = 0
        self.last_request: object | None = None

    def stream(self, *, request: object) -> AsyncIterator[SemanticChunk]:
        self.last_request = request
        return self._generate()

    async def _generate(self) -> AsyncIterator[SemanticChunk]:
        chunks = self._respond(self.calls)
        self.calls += 1
        for chunk in chunks:
            yield chunk


class _FakeTools(ToolRunnerPort):
    """脚本化 ToolRunner：按调用序号产出 ToolResult（无真实执行）。"""

    def __init__(
        self,
        respond: Callable[[ToolCallRequest, int], ToolResult],
        descriptors: dict[str, ToolDescriptor] | None = None,
    ) -> None:
        self._respond = respond
        self._descriptors = descriptors or {
            "tool.a": ToolDescriptor(
                qualified_name="tool.a",
                short_name="tool.a",
                namespace="test",
                description="测试工具 A",
                parameters={},
                source=ToolSource.META,
                tier=0,
            )
        }
        self.calls = 0

    def exposed_tools(self) -> list[ChatToolSpec]:
        return [
            ChatToolSpec(
                function=ToolFunction(
                    name=name, description=desc.description, parameters=desc.parameters
                )
            )
            for name, desc in self._descriptors.items()
        ]

    def get_descriptor(self, name: str) -> ToolDescriptor | None:
        return self._descriptors.get(name)

    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]:
        results = [self._respond(call, self.calls) for call in calls]
        self.calls += 1
        return results


class _FakeEvents:
    """记录发射的事件（EventSink 桩）。"""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    async def emit(self, event: RunEvent) -> None:
        self.events.append(event)


def _request(max_iterations: int = 20) -> PhaseExecutionRequest:
    budget = BudgetState(
        limits=BudgetLimits(
            max_iterations=max_iterations,
            max_llm_calls=30,
            max_tool_calls=40,
            max_total_tokens=100000,
            max_input_tokens=80000,
            max_duration_seconds=300.0,
            max_repair_attempts=2,
            finalization_reserve_tokens=5000,
        )
    )
    return PhaseExecutionRequest(
        run_id="run-1",
        phase_instance_id="p1",
        phase_goal="完成测试查询",
        allowed_tools=["tool.a"],
        budget=budget,
    )


def _executor(
    llm: _FakeLLM,
    tools: _FakeTools,
    *,
    progress_threshold: int = 3,
) -> BoundedReActExecutor:
    return BoundedReActExecutor(
        llm=llm,
        tools=tools,
        events=_FakeEvents(),
        progress_threshold=progress_threshold,
    )


def _tool_call(name: str, arguments: str = "{}", call_id: str = "c1") -> list[SemanticChunk]:
    call = ToolCall(index=0, id=call_id, name=name, arguments=arguments)
    return [ToolCallsChunk(tool_calls=[call])]


async def _run(executor: BoundedReActExecutor, request: PhaseExecutionRequest) -> ReactGraphState:
    graph: CompiledStateGraph[ReactGraphState] = build_react_subgraph(executor)
    initial = ReactGraphState(request=request, budget=request.budget)
    final = await graph.ainvoke(initial)
    return ReactGraphState.model_validate(final)


# ---- §24 场景 1：工具调用后正常完成 ----
async def test_graph_normal_completion_after_tool_call() -> None:
    def respond(call_index: int) -> list[SemanticChunk]:
        if call_index == 0:
            return _tool_call("tool.a", '{"q": "x"}', call_id="c1")
        return _tool_call(
            "complete_phase", '{"output": {"score": 1}, "summary": "完成"}', call_id="c2"
        )

    def tool_result(_call: ToolCallRequest, index: int) -> ToolResult:
        return ToolResult(call_id=_call.call_id, tool_name=_call.tool_name, ok=True, content="数据")

    state = await _run(_executor(_FakeLLM(respond), _FakeTools(tool_result)), _request())
    assert state.outcome is not None
    assert state.outcome.outcome_type == PhaseExecutionOutcomeType.CANDIDATE_COMPLETED
    assert state.outcome.candidate_output == {"score": 1}


# ---- §24 场景 2：无限重复同一 Action → no_progress 终止 ----
async def test_graph_infinite_repeat_terminates_no_progress() -> None:
    def respond(_call_index: int) -> list[SemanticChunk]:
        return _tool_call("tool.a", '{"q": "same"}', call_id="c1")

    def tool_result(_call: ToolCallRequest, _index: int) -> ToolResult:
        return ToolResult(
            call_id=_call.call_id, tool_name=_call.tool_name, ok=True, content="相同结果"
        )

    state = await _run(_executor(_FakeLLM(respond), _FakeTools(tool_result)), _request())
    assert state.outcome is not None
    assert state.outcome.outcome_type == PhaseExecutionOutcomeType.PARTIAL_NO_PROGRESS
    assert "no_progress" in state.outcome.reason_code


# ---- §24 场景 3：A/B 交替但无进展 → 预算硬边界终止 ----
async def test_graph_alternating_tools_terminates_by_budget() -> None:
    def respond(call_index: int) -> list[SemanticChunk]:
        name = "tool.a" if call_index % 2 == 0 else "tool.b"
        return _tool_call(name, '{"q": "x"}', call_id=f"c{call_index}")

    def tool_result(_call: ToolCallRequest, _index: int) -> ToolResult:
        return ToolResult(
            call_id=_call.call_id, tool_name=_call.tool_name, ok=True, content="无进展"
        )

    tools = _FakeTools(tool_result)
    request = _request(max_iterations=3)
    state = await _run(_executor(_FakeLLM(respond), tools, progress_threshold=5), request)
    assert state.outcome is not None
    assert state.outcome.outcome_type in {
        PhaseExecutionOutcomeType.PARTIAL_BUDGET,
        PhaseExecutionOutcomeType.PARTIAL_NO_PROGRESS,
    }


# ---- §24 场景 4：重复 Action 但每次有新进展 → 允许继续并完成 ----
async def test_graph_repeated_action_with_new_progress_completes() -> None:
    def respond(call_index: int) -> list[SemanticChunk]:
        if call_index < 2:
            return _tool_call("tool.a", '{"q": "x"}', call_id="c1")
        return _tool_call("complete_phase", '{"output": {"ok": true}}', call_id="c2")

    def tool_result(_call: ToolCallRequest, index: int) -> ToolResult:
        return ToolResult(
            call_id=_call.call_id,
            tool_name=_call.tool_name,
            ok=True,
            content=f"证据{index}",
        )

    state = await _run(_executor(_FakeLLM(respond), _FakeTools(tool_result)), _request())
    assert state.outcome is not None
    assert state.outcome.outcome_type == PhaseExecutionOutcomeType.CANDIDATE_COMPLETED


# ---- §24 场景 5：预算硬边界 → 确定性终止（不再调用 LLM/工具）----
async def test_graph_hard_budget_terminates() -> None:
    def respond(_call_index: int) -> list[SemanticChunk]:
        return _tool_call("tool.a", '{"q": "x"}')

    def tool_result(_call: ToolCallRequest, _index: int) -> ToolResult:
        return ToolResult(call_id=_call.call_id, tool_name=_call.tool_name, ok=True, content="数据")

    llm = _FakeLLM(respond)
    state = await _run(_executor(llm, _FakeTools(tool_result)), _request(max_iterations=2))
    assert state.outcome is not None
    assert state.budget.usage.iterations <= 2


# ---- §24 场景 6：thinking_enabled 透传给 LLM 请求 ----
async def test_graph_forwards_thinking_enabled_to_llm() -> None:
    def respond(call_index: int) -> list[SemanticChunk]:
        if call_index == 0:
            return _tool_call("tool.a", '{"q": "x"}', call_id="c1")
        return _tool_call("complete_phase", '{"output": {"ok": true}}', call_id="c2")

    def tool_result(_call: ToolCallRequest, _index: int) -> ToolResult:
        return ToolResult(call_id=_call.call_id, tool_name=_call.tool_name, ok=True, content="数据")

    llm = _FakeLLM(respond)
    request = _request().model_copy(update={"thinking_enabled": False})
    state = await _run(_executor(llm, _FakeTools(tool_result)), request)
    assert state.outcome is not None
    assert llm.last_request is not None
    assert llm.last_request.thinking is False


# ---- §24 场景 7：工具结果回传按 tool_message_max_chars 截断 ----
async def test_graph_truncates_tool_message_content() -> None:
    def respond(call_index: int) -> list[SemanticChunk]:
        if call_index == 0:
            return _tool_call("tool.a", '{"q": "x"}', call_id="c1")
        return _tool_call("complete_phase", '{"output": {"ok": true}}', call_id="c2")

    def tool_result(_call: ToolCallRequest, _index: int) -> ToolResult:
        return ToolResult(
            call_id=_call.call_id,
            tool_name=_call.tool_name,
            ok=True,
            content="x" * 3000,
        )

    request = _request().model_copy(update={"tool_message_max_chars": 100})
    state = await _run(_executor(_FakeLLM(respond), _FakeTools(tool_result)), request)
    tool_messages = [m for m in state.messages if m.role == "tool"]
    assert len(tool_messages) == 1
    content = tool_messages[0].content or ""
    assert len(content) == 105  # 100 + "…(截断)"(5 字符)
    assert content.endswith("…(截断)")
