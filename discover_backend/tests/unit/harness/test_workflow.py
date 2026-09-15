"""多阶段 Workflow 测试（W8，§9）。

Fake LLM 脚本化跑通：两阶段顺序执行、阶段间 input_bindings 只读绑定上游
PhaseOutput、非完成结果终止后续阶段、执行器注册表解析。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from app.environment.tools.broker import ToolCallRequest, ToolResult
from app.environment.tools.models import ToolDescriptor, ToolSource
from app.harness.events.run_events import RunEvent
from app.harness.execution.pipeline import (
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolPreflightResult,
    ToolRuntime,
)
from app.harness.models import BudgetLimits, BudgetState
from app.harness.react.executor import BoundedReActExecutor
from app.harness.react.ports import ActionGatewayPort
from app.harness.workflow.compiler import WorkflowRunner
from app.harness.workflow.definition import (
    PhaseDefinition,
    PhaseExecutorType,
    WorkflowDefinition,
)
from app.harness.workflow.executors import PhaseExecutorRegistry, ReactPhaseExecutor
from app.llm.models import ChatToolSpec, ToolFunction
from app.llm.stream_parser import SemanticChunk, ToolCall, ToolCallsChunk


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
    """脚本化工具代理：tool.a 返回「数据」。"""

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


class _FakeActions(ActionGatewayPort):
    """把 _FakeTools 包装为 ActionGatewayPort（经 ToolRuntime 走真实管线边界）。"""

    def __init__(self, tools: _FakeTools, progress_threshold: int = 3) -> None:
        self._tools = tools
        self._progress_threshold = progress_threshold

    def _runtime(self) -> ToolRuntime:
        async def _noop(_event: RunEvent) -> None:
            return None

        return ToolRuntime(
            broker=self._tools,
            emit=_noop,
            progress_threshold=self._progress_threshold,
        )

    def exposed_tools(self) -> list[ChatToolSpec]:
        return self._tools.exposed_tools()

    def get_descriptor(self, name: str) -> ToolDescriptor | None:
        return self._tools.get_descriptor(name)

    async def preflight(self, request: ToolExecutionRequest) -> ToolPreflightResult:
        return await self._runtime().preflight(request)

    async def execute_batch(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return await self._runtime().execute_prepared(request, request.calls, [])


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
        BoundedReActExecutor(llm=llm, actions=_FakeActions(_FakeTools()), events=_FakeEvents())
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
            from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

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
            from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

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


async def test_workflow_falls_back_to_render_with_context() -> None:
    """非完成阶段声明 fallback_phase 时，Harness 确定性跳到 render，而非空正文终止。"""
    from app.harness.models import (
        PhaseExecutionOutcome,
        PhaseExecutionOutcomeType,
        PhaseExecutionRequest,
    )

    captured: dict[str, object] = {}

    class _PartialReact:
        async def execute(self, definition: object, request: object) -> PhaseExecutionOutcome:
            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.PARTIAL_BUDGET,
                context_payload="tool: 采集数据",
                reason_code="soft_budget:llm_calls",
            )

    class _Render:
        async def execute(
            self, definition: object, request: PhaseExecutionRequest
        ) -> PhaseExecutionOutcome:
            captured["context_summary"] = request.context_summary
            captured["phase_input"] = request.phase_input
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
                answer="信息卡正文",
                reason_code="render_completed",
            )

    registry = PhaseExecutorRegistry(
        {
            PhaseExecutorType.REACT: _PartialReact(),
            PhaseExecutorType.RENDER: _Render(),
        }
    )
    runner = WorkflowRunner(executors=registry)
    definition = WorkflowDefinition(
        workflow_id="wf-fallback",
        phases=[
            PhaseDefinition(
                phase_id="research",
                executor_type=PhaseExecutorType.REACT,
                fallback_phase="render",
            ),
            PhaseDefinition(phase_id="render", executor_type=PhaseExecutorType.RENDER),
        ],
    )
    result = await runner.run(
        definition,
        run_id="r1",
        phase_input={"user_goal": "调研两家企业"},
        budget=_budget(),
        allowed_tools=[],
    )
    assert result.final_outcome is not None
    assert result.final_outcome.answer == "信息卡正文"
    assert captured["context_summary"] == "tool: 采集数据"
    assert captured["phase_input"] == {"user_goal": "调研两家企业"}


async def test_render_phase_executor_streams_text_without_tools() -> None:
    """render 阶段关闭工具，只流式产出正文。"""
    from app.harness.models import PhaseExecutionRequest
    from app.harness.workflow.executors import RenderPhaseExecutor
    from app.llm.models import ChatRequest
    from app.llm.stream_parser import TextChunk, UsageChunk

    captured_request: ChatRequest | None = None

    class _RenderLLM:
        def stream(self, *, request: ChatRequest) -> AsyncIterator[SemanticChunk]:
            nonlocal captured_request
            captured_request = request
            return self._generate()

        async def _generate(self) -> AsyncIterator[SemanticChunk]:
            yield TextChunk(text="最终")
            yield TextChunk(text="答案")
            yield UsageChunk(input_tokens=3, output_tokens=2, total_tokens=5)

    displayed: list[str] = []
    executor = RenderPhaseExecutor(llm=_RenderLLM(), display_text=displayed.append)
    request = PhaseExecutionRequest(
        run_id="r1",
        phase_instance_id="render",
        phase_goal="生成信息卡",
        system_prompt="按三段式输出",
        phase_input={"user_goal": "调研两家企业"},
        context_summary="tool: 采集数据",
        allowed_tools=["tool.a"],
        thinking_enabled=False,
        budget=_budget(),
    )
    outcome = await executor.execute(
        PhaseDefinition(phase_id="render", executor_type=PhaseExecutorType.RENDER), request
    )
    assert outcome.answer == "最终答案"
    assert displayed == ["最终", "答案"]
    assert captured_request is not None
    assert captured_request.tools == []
    assert captured_request.thinking is False


async def test_run_skill_workflow_research_then_render() -> None:
    """端到端：research 阶段用满 LLM 调用预算后，Harness 强制 fallback 到 render 并产出正文。"""
    from app.harness.agent_runner import run_skill_workflow
    from app.harness.models import PhaseExecutionRequest
    from app.llm.stream_parser import TextChunk, UsageChunk

    def respond(call_index: int) -> list[SemanticChunk]:
        if call_index == 0:
            return _tool_call("tool.a", '{"q": "x"}', call_id="c1")
        return [
            TextChunk(text="最终答案"),
            UsageChunk(input_tokens=3, output_tokens=2, total_tokens=5),
        ]

    budget = _budget()
    budget.limits.max_llm_calls = 1
    request = PhaseExecutionRequest(
        run_id="r1",
        phase_instance_id="main",
        phase_goal="research",
        system_prompt="系统提示",
        phase_input={"user_goal": "调研企业"},
        allowed_tools=["tool.a"],
        thinking_enabled=False,
        budget=budget,
    )
    definition = WorkflowDefinition(
        workflow_id="wf-e2e",
        phases=[
            PhaseDefinition(
                phase_id="research",
                executor_type=PhaseExecutorType.REACT,
                inherit_tools=True,
                fallback_phase="render",
            ),
            PhaseDefinition(phase_id="render", executor_type=PhaseExecutorType.RENDER),
        ],
    )
    outcome = await run_skill_workflow(
        llm=_FakeLLM(respond),
        actions=_FakeActions(_FakeTools()),
        events=_FakeEvents(),
        request=request,
        definition=definition,
    )
    assert outcome is not None
    assert outcome.answer == "最终答案"


async def test_workflow_output_contract_repairs_render() -> None:
    """render 产出后确定性执行输出门禁；首次失败触发一次修复后重跑。"""
    from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

    gate_calls: list[str] = []

    class _GateRunner:
        async def run_gate(self, *, gate_id: str, data: dict[str, object]) -> ToolResult:
            del gate_id
            gate_calls.append(str(data.get("answer", "")))
            if len(gate_calls) == 1:
                return ToolResult(
                    call_id="g",
                    tool_name="gate_final_qa",
                    ok=False,
                    message='{"passed": false, "errors": ["第 1 张卡过短"]}',
                    suggestion="修复",
                )
            return ToolResult(call_id="g", tool_name="gate_final_qa", ok=True, content="通过")

    render_calls: list[int] = []

    class _Render:
        async def execute(self, definition: object, request: object) -> object:
            del definition, request
            render_calls.append(1)
            answer = "第一版" if len(render_calls) == 1 else "修复版"
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
                answer=answer,
                reason_code="render_completed",
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry({PhaseExecutorType.RENDER: _Render()}),
        max_repair_attempts=1,
        gate_runner=_GateRunner(),
    )
    definition = WorkflowDefinition(
        workflow_id="wf-gate",
        phases=[PhaseDefinition(phase_id="render", executor_type=PhaseExecutorType.RENDER)],
        output_contract_refs=["final_qa"],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.final_outcome is not None
    assert result.final_outcome.answer == "修复版"
    assert gate_calls == ["第一版", "修复版"]
    assert render_calls == [1, 1]


async def test_workflow_output_contract_exhausts_repairs() -> None:
    """门禁持续失败时受 max_repair_attempts 有界约束，不无限返工。"""
    from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

    class _AlwaysFailGate:
        async def run_gate(self, *, gate_id: str, data: dict[str, object]) -> ToolResult:
            del gate_id, data
            return ToolResult(
                call_id="g",
                tool_name="gate_final_qa",
                ok=False,
                message='{"passed": false, "errors": ["超限"]}',
                suggestion="修复",
            )

    render_calls: list[int] = []

    class _Render:
        async def execute(self, definition: object, request: object) -> object:
            del definition, request
            render_calls.append(1)
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
                answer=f"第{len(render_calls)}版",
                reason_code="render_completed",
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry({PhaseExecutorType.RENDER: _Render()}),
        max_repair_attempts=1,
        gate_runner=_AlwaysFailGate(),
    )
    definition = WorkflowDefinition(
        workflow_id="wf-gate-fail",
        phases=[PhaseDefinition(phase_id="render", executor_type=PhaseExecutorType.RENDER)],
        output_contract_refs=["final_qa"],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.reason_code == "contract_failed:final_qa"
    assert render_calls == [1, 1]
    assert result.final_outcome is not None
    assert result.final_outcome.answer == "第2版"


async def test_workflow_output_contract_receives_bound_input() -> None:
    """输出契约上下文须同时携带最终正文与本阶段绑定的结构化输入。"""
    from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

    received: list[dict[str, object]] = []

    class _GateRunner:
        async def run_gate(self, *, gate_id: str, data: dict[str, object]) -> ToolResult:
            del gate_id
            received.append(dict(data))
            return ToolResult(
                call_id="g", tool_name="gate_report_structure", ok=True, content="通过"
            )

    class _Research:
        async def execute(self, definition: object, request: object) -> object:
            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
                candidate_output={"report": {"composite_score": 9.5}},
                reason_code="candidate_completed",
            )

    class _Render:
        async def execute(self, definition: object, request: object) -> object:
            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
                answer="报告正文",
                reason_code="render_completed",
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry(
            {
                PhaseExecutorType.REACT: _Research(),
                PhaseExecutorType.RENDER: _Render(),
            }
        ),
        max_repair_attempts=1,
        gate_runner=_GateRunner(),
    )
    definition = WorkflowDefinition(
        workflow_id="wf-bound",
        phases=[
            PhaseDefinition(phase_id="research", executor_type=PhaseExecutorType.REACT),
            PhaseDefinition(
                phase_id="render",
                executor_type=PhaseExecutorType.RENDER,
                input_bindings={"research.report": "report"},
            ),
        ],
        output_contract_refs=["report_structure"],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.final_outcome is not None
    assert result.final_outcome.answer == "报告正文"
    assert received == [{"answer": "报告正文", "report": {"composite_score": 9.5}}]


async def test_workflow_repairs_missing_required_field_then_continues() -> None:
    """中间阶段缺必填字段触发一次结构修复，修复后继续后续阶段。"""
    from app.harness.models import (
        PhaseExecutionOutcome,
        PhaseExecutionOutcomeType,
        PhaseExecutionRequest,
    )

    calls: list[tuple[str, int, str]] = []

    class _RepairingReact:
        def __init__(self) -> None:
            self._attempts = 0

        async def execute(
            self, definition: object, request: PhaseExecutionRequest
        ) -> PhaseExecutionOutcome:
            phase_id = request.phase_instance_id
            attempt = request.attempt
            goal = request.phase_goal
            calls.append((phase_id, attempt, goal))
            if phase_id == "p1":
                self._attempts += 1
                if self._attempts == 1:
                    return PhaseExecutionOutcome(
                        outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
                        candidate_output={},
                        output_schema={"required": ["title"]},
                    )
                return PhaseExecutionOutcome(
                    outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
                    candidate_output={"title": "报告"},
                    output_schema={"required": ["title"]},
                )
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
                candidate_output={"ok": True},
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry({PhaseExecutorType.REACT: _RepairingReact()}),
        max_repair_attempts=1,
    )
    definition = WorkflowDefinition(
        workflow_id="wf-repair",
        phases=[
            PhaseDefinition(phase_id="p1", goal="g1", output_schema={"required": ["title"]}),
            PhaseDefinition(phase_id="p2", goal="g2"),
        ],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.completed_phase_ids == ["p1", "p2"]
    assert [phase_id for phase_id, _, _ in calls] == ["p1", "p1", "p2"]
    assert calls[1][1] == 1  # 重跑 attempt=1
    assert "修复" in calls[1][2]  # 重跑 phase_goal 携带修复说明


async def test_workflow_structural_failure_terminates_without_fallback() -> None:
    """修复耗尽且无 fallback → 终止，reason_code 含 contract_failed。"""
    from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

    class _AlwaysBadReact:
        async def execute(self, definition: object, request: object) -> PhaseExecutionOutcome:
            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
                candidate_output={},
                output_schema={"required": ["title"]},
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry({PhaseExecutorType.REACT: _AlwaysBadReact()}),
        max_repair_attempts=1,
    )
    definition = WorkflowDefinition(
        workflow_id="wf-structural-fail",
        phases=[
            PhaseDefinition(phase_id="p1", goal="g1", output_schema={"required": ["title"]}),
            PhaseDefinition(phase_id="p2", goal="g2"),
        ],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.completed_phase_ids == []
    assert result.final_outcome is not None
    assert result.final_outcome.outcome_type == PhaseExecutionOutcomeType.CANDIDATE_COMPLETED
    assert result.reason_code == "contract_failed:p1"


async def test_workflow_structural_failure_degrades_to_fallback() -> None:
    """修复耗尽且有 fallback_phase → 确定性跳转，context_payload 透传。"""
    from app.harness.models import (
        PhaseExecutionOutcome,
        PhaseExecutionOutcomeType,
        PhaseExecutionRequest,
    )

    captured: dict[str, object] = {}

    class _BadReactWithFallback:
        async def execute(self, definition: object, request: object) -> PhaseExecutionOutcome:
            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
                candidate_output={},
                output_schema={"required": ["title"]},
                context_payload="采集到的上下文",
            )

    class _Render:
        async def execute(
            self, definition: object, request: PhaseExecutionRequest
        ) -> PhaseExecutionOutcome:
            captured["context_summary"] = request.context_summary
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
                answer="降级正文",
                reason_code="render_completed",
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry(
            {
                PhaseExecutorType.REACT: _BadReactWithFallback(),
                PhaseExecutorType.RENDER: _Render(),
            }
        ),
        max_repair_attempts=1,
    )
    definition = WorkflowDefinition(
        workflow_id="wf-structural-degrade",
        phases=[
            PhaseDefinition(
                phase_id="research",
                executor_type=PhaseExecutorType.REACT,
                output_schema={"required": ["title"]},
                fallback_phase="render",
            ),
            PhaseDefinition(phase_id="render", executor_type=PhaseExecutorType.RENDER),
        ],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.final_outcome is not None
    assert result.final_outcome.answer == "降级正文"
    assert captured["context_summary"] == "采集到的上下文"


async def test_workflow_empty_schema_skips_structural_gate() -> None:
    """output_schema 为空 → 不触发结构校验，行为与现状一致。"""
    from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

    class _EmptySchemaReact:
        async def execute(self, definition: object, request: object) -> PhaseExecutionOutcome:
            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
                candidate_output=None,
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry({PhaseExecutorType.REACT: _EmptySchemaReact()})
    )
    definition = WorkflowDefinition(
        workflow_id="wf-empty-schema",
        phases=[PhaseDefinition(phase_id="p1", goal="g1")],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.completed_phase_ids == ["p1"]
    assert result.final_outcome is None


async def test_gate_reads_outcome_schema_not_phase_schema() -> None:
    """闸门校验源与 Verifier 同源（outcome.output_schema）；执行器不回传时跳过校验。"""
    from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

    class _NoEchoReact:
        async def execute(self, definition: object, request: object) -> PhaseExecutionOutcome:
            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
                candidate_output={},  # 缺 required.title，但 outcome 未回传 output_schema
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry({PhaseExecutorType.REACT: _NoEchoReact()}),
        max_repair_attempts=1,
    )
    definition = WorkflowDefinition(
        workflow_id="wf-no-echo",
        phases=[PhaseDefinition(phase_id="p1", goal="g1", output_schema={"required": ["title"]})],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    # phase.output_schema 声明了 required，但 outcome.output_schema 为空 →
    # 闸门与 Verifier 一致地跳过校验，正常推进。
    assert result.completed_phase_ids == ["p1"]


async def test_workflow_output_contract_aggregates_refs_in_reason() -> None:
    """多门禁失败聚合后 reason_code 携带全部 refs（decide_repair 收敛）。"""
    from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

    class _AlwaysFailGate:
        async def run_gate(self, *, gate_id: str, data: dict[str, object]) -> ToolResult:
            del data
            return ToolResult(
                call_id="g",
                tool_name=f"gate_{gate_id}",
                ok=False,
                message='{"passed": false, "errors": ["失败"]}',
                suggestion="修复",
            )

    class _Render:
        async def execute(self, definition: object, request: object) -> PhaseExecutionOutcome:
            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
                answer="正文",
                reason_code="render_completed",
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry({PhaseExecutorType.RENDER: _Render()}),
        max_repair_attempts=1,
        gate_runner=_AlwaysFailGate(),
    )
    definition = WorkflowDefinition(
        workflow_id="wf-gate-multi",
        phases=[PhaseDefinition(phase_id="render", executor_type=PhaseExecutorType.RENDER)],
        output_contract_refs=["gate_a", "gate_b"],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.reason_code == "contract_failed:gate_a,gate_b"


async def test_workflow_output_contract_passed_reason() -> None:
    """门禁通过且 render 无 reason_code 时，落回 output_contract_passed（非 contract_ok）。"""
    from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType

    class _PassGate:
        async def run_gate(self, *, gate_id: str, data: dict[str, object]) -> ToolResult:
            del gate_id, data
            return ToolResult(call_id="g", tool_name="gate", ok=True, content="通过")

    class _Render:
        async def execute(self, definition: object, request: object) -> PhaseExecutionOutcome:
            del definition, request
            return PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
                answer="正文",
            )

    runner = WorkflowRunner(
        executors=PhaseExecutorRegistry({PhaseExecutorType.RENDER: _Render()}),
        max_repair_attempts=1,
        gate_runner=_PassGate(),
    )
    definition = WorkflowDefinition(
        workflow_id="wf-gate-pass",
        phases=[PhaseDefinition(phase_id="render", executor_type=PhaseExecutorType.RENDER)],
        output_contract_refs=["final_qa"],
    )
    result = await runner.run(
        definition, run_id="r1", phase_input={}, budget=_budget(), allowed_tools=[]
    )
    assert result.reason_code == "output_contract_passed"
