"""多阶段 Workflow 测试（W8，§9）。

Fake LLM 脚本化跑通：两阶段顺序执行、阶段间 input_bindings 只读绑定上游
PhaseOutput、非完成结果终止后续阶段、执行器注册表解析。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from app.capabilities.llm.models import ChatToolSpec, ToolFunction
from app.capabilities.llm.stream_parser import SemanticChunk, ToolCall, ToolCallsChunk
from app.capabilities.tools.broker import ToolCallRequest, ToolResult
from app.capabilities.tools.descriptor import ToolDescriptor, ToolSource
from app.runtime.events.run_events import RunEvent
from app.runtime.models import BudgetLimits, BudgetState
from app.runtime.react.executor import BoundedReActExecutor
from app.runtime.workflow.compiler import WorkflowRunner
from app.runtime.workflow.definition import PhaseDefinition, PhaseExecutorType, WorkflowDefinition
from app.runtime.workflow.executors import PhaseExecutorRegistry, ReactPhaseExecutor


class _FakeLLM:
    """脚本化 LLM：按调用序号产出语义分片（Fake LLM，无网络）。"""

    def __init__(self, respond: Callable[[int], list[SemanticChunk]]) -> None:
        self._respond = respond
        self.calls = 0

    def stream(self, *, request: object) -> AsyncIterator[SemanticChunk]:
        del request
        return self._generate()

    async def _generate(self) -> AsyncIterator[SemanticChunk]:
        chunks = self._respond(self.calls)
        self.calls += 1
        for chunk in chunks:
            yield chunk


class _FakeTools:
    """脚本化 ToolRunner：tool.a 返回「数据」。"""

    def exposed_tools(self) -> list[ChatToolSpec]:
        return [
            ChatToolSpec(
                function=ToolFunction(name="tool.a", description="测试工具", parameters={})
            )
        ]

    def get_descriptor(self, name: str) -> ToolDescriptor | None:
        return ToolDescriptor(
            qualified_name=name,
            short_name=name,
            namespace="test",
            description="测试工具",
            parameters={},
            source=ToolSource.META,
            tier=0,
        )

    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]:
        return [
            ToolResult(call_id=call.call_id, tool_name=call.tool_name, ok=True, content="数据")
            for call in calls
        ]


class _FakeEvents:
    async def emit(self, event: RunEvent) -> None:
        del event


def _budget() -> BudgetState:
    return BudgetState(
        limits=BudgetLimits(
            max_iterations=20,
            max_llm_calls=30,
            max_tool_calls=40,
            max_total_tokens=100000,
            max_input_tokens=80000,
            max_duration_seconds=300.0,
            max_repair_attempts=2,
            finalization_reserve_tokens=5000,
        )
    )


def _tool_call(name: str, arguments: str = "{}", call_id: str = "c1") -> list[SemanticChunk]:
    call = ToolCall(index=0, id=call_id, name=name, arguments=arguments)
    return [ToolCallsChunk(tool_calls=[call])]


async def test_workflow_runs_two_phases_in_order() -> None:
    """两阶段顺序执行：每阶段 react → complete_phase（共用同一执行器）。"""

    def respond(call_index: int) -> list[SemanticChunk]:
        # 每阶段内：第 0 次调用工具，第 1 次 complete_phase
        if call_index % 2 == 0:
            return _tool_call("tool.a")
        return _tool_call("complete_phase", '{"output": {"ok": true}}')

    llm = _FakeLLM(respond)
    react = ReactPhaseExecutor(
        BoundedReActExecutor(llm=llm, tools=_FakeTools(), events=_FakeEvents())
    )
    runner = WorkflowRunner(executors=PhaseExecutorRegistry({PhaseExecutorType.REACT: react}))
    definition = WorkflowDefinition(
        workflow_id="w1",
        phases=[
            PhaseDefinition(phase_id="p1", goal="第一阶段"),
            PhaseDefinition(
                phase_id="p2",
                goal="第二阶段",
                input_bindings={"p1.output": "first_result"},
            ),
        ],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.completed_phase_ids == ["p1", "p2"]
    assert result.final_outcome is None


async def test_workflow_binding_passes_upstream_output() -> None:
    """§9.4：下一阶段只通过显式 input_bindings 读取上游 PhaseOutput。"""
    captured: list[dict[str, object]] = []

    class _CapturingReact:
        async def execute(self, definition: object, request: object) -> object:
            from app.runtime.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

            captured.append(getattr(request, "phase_input", {}))
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
                candidate_output={"score": 0.9},
            )

    registry = PhaseExecutorRegistry({PhaseExecutorType.REACT: _CapturingReact()})  # type: ignore[arg-type]  # 测试桩
    runner = WorkflowRunner(executors=registry)
    definition = WorkflowDefinition(
        workflow_id="w1",
        phases=[
            PhaseDefinition(phase_id="p1", goal="g1"),
            PhaseDefinition(phase_id="p2", goal="g2", input_bindings={"p1.score": "s"}),
        ],
    )
    await runner.run(definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[])
    # 第二个阶段收到的 phase_input 已含 p1 的输出字段 s=0.9
    assert captured[1]["s"] == 0.9


async def test_workflow_stops_on_non_completion() -> None:
    """非完成结果（FAILED）终止后续阶段。"""

    class _FailingReact:
        async def execute(self, definition: object, request: object) -> object:
            from app.runtime.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.FAILED, reason_code="boom"
            )

    registry = PhaseExecutorRegistry({PhaseExecutorType.REACT: _FailingReact()})  # type: ignore[arg-type]  # 测试桩
    runner = WorkflowRunner(executors=registry)
    definition = WorkflowDefinition(
        workflow_id="w1",
        phases=[
            PhaseDefinition(phase_id="p1", goal="g1"),
            PhaseDefinition(phase_id="p2", goal="g2"),
        ],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.completed_phase_ids == []
    assert result.final_outcome is not None
    assert result.final_outcome.reason_code == "boom"
