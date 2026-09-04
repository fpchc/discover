"""Agent 技能包 → 单阶段 ReAct 接线测试。

覆盖核心接线（react-runtime-v2-architecture §9.4 / §18.4）：
- 装配层系统提示（AGENT.md + SKILL.md + 平台红线）真正注入 ReAct LLM 首条消息，
  证明「ReAct 配合 agents 技能包配置」而非硬编码通用提示；
- AgentAssembler 装配 / build_agent_budget 预算映射 / _outcome_answer /
  _history_summary 适配。

全部 Fake LLM / Fake ToolRunner，无网络无 DB（CLAUDE.md §12）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace

from app.capabilities.llm.models import ChatToolSpec, ToolFunction
from app.capabilities.llm.stream_parser import (
    SemanticChunk,
    ToolCall,
    ToolCallsChunk,
)
from app.capabilities.tools.broker import ToolCallRequest, ToolResult
from app.capabilities.tools.descriptor import ToolDescriptor, ToolSource
from app.config.settings import Settings
from app.interfaces.http.chat_execution import (
    _history_summary,
    _outcome_answer,
)
from app.runtime.agent_runner import build_agent_budget
from app.runtime.events.run_events import RunEvent
from app.runtime.graph import build_react_subgraph
from app.runtime.models import (
    BudgetState,
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
)
from app.runtime.react.executor import (
    BoundedReActExecutor,
    EventSinkPort,
    LLMRunnerPort,
    ReactGraphState,
    ToolRunnerPort,
)
from langgraph.graph.state import CompiledStateGraph


class _CapturingLLM(LLMRunnerPort):
    """脚本化 LLM：捕获每次 ChatRequest，按调用序号产出语义分片。"""

    def __init__(self, respond: Callable[[int], list[SemanticChunk]]) -> None:
        self._respond = respond
        self.calls = 0
        self.requests: list[object] = []

    def stream(self, *, request: object) -> AsyncIterator[SemanticChunk]:
        self.requests.append(request)
        return self._generate()

    async def _generate(self) -> AsyncIterator[SemanticChunk]:
        chunks = self._respond(self.calls)
        self.calls += 1
        for chunk in chunks:
            yield chunk


class _FakeTools(ToolRunnerPort):
    """脚本化 ToolRunner：descriptor 目录固定，execute 恒成功。"""

    def __init__(self) -> None:
        self._descriptors = {
            "discover.client-finder.script.score_calculator": ToolDescriptor(
                qualified_name="discover.client-finder.script.score_calculator",
                short_name="score_calculator",
                namespace="discover.client-finder.script",
                description="八维评分计算器",
                parameters={},
                source=ToolSource.SCRIPT,
                tier=1,
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
        self.calls += 1
        return [
            ToolResult(call_id=call.call_id, tool_name=call.tool_name, ok=True, content="数据")
            for call in calls
        ]


class _RecordingSink(EventSinkPort):
    """记录发射的 RunEvent（供断言 LLMUsageUpdated 聚合）。"""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    async def emit(self, event: RunEvent) -> None:
        self.events.append(event)


def _request(budget: BudgetState, *, system_prompt: str = "") -> PhaseExecutionRequest:
    return PhaseExecutionRequest(
        run_id="run-1",
        phase_instance_id="client-finder",
        phase_goal="完成客户发现任务",
        system_prompt=system_prompt,
        phase_input={"user_goal": "找电子信息产业链潜在客户"},
        context_summary="最近对话：用户需要一份客户发现报告。",
        allowed_tools=["discover.client-finder.script.score_calculator"],
        budget=budget,
    )


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        agent_max_iterations=12,
        agent_max_llm_calls=15,
        agent_max_tool_calls=18,
        agent_max_total_tokens=50000,
        agent_max_input_tokens=40000,
        agent_max_duration_seconds=120.0,
        agent_max_repair_attempts=1,
        agent_finalization_reserve_tokens=2000,
        agent_context_summary_max_messages=5,
        agent_context_summary_max_chars=2000,
    )


def _tool_call(name: str, arguments: str = "{}", call_id: str = "c1") -> list[SemanticChunk]:
    call = ToolCall(index=0, id=call_id, name=name, arguments=arguments)
    return [ToolCallsChunk(tool_calls=[call])]


async def _run(executor: BoundedReActExecutor, request: PhaseExecutionRequest) -> ReactGraphState:
    graph: CompiledStateGraph[ReactGraphState] = build_react_subgraph(executor)
    initial = ReactGraphState(request=request, budget=request.budget)
    final = await graph.ainvoke(initial)
    return ReactGraphState.model_validate(final)


# ---- 核心：技能包系统提示注入 ReAct LLM 首条消息 ----
async def test_skill_system_prompt_injected_into_react_llm() -> None:
    """装配层系统提示（技能包配置）必须进入 ReAct 的首条 LLM 系统消息。

    这是「ReAct 配合 agents 技能包配置使用」的直接验证：executor 不得使用
    硬编码通用提示替代技能包正文。
    """
    skill_prompt = (
        "# 智能体：客户发现\n你服务电子信息产业链销售人员。\n"
        "# 技能：客户发现工作流\n先澄清再搜索，评分必须走 score_calculator。\n"
        "# 平台红线（强制）\n严禁出现内部 agent_id。"
    )

    def respond(call_index: int) -> list[SemanticChunk]:
        if call_index == 0:
            return _tool_call(
                "discover.client-finder.script.score_calculator",
                '{"input": "客户A"}',
                call_id="t1",
            )
        return _tool_call("submit_final_answer", '{"answer": "报告完成"}', call_id="t2")

    llm = _CapturingLLM(respond)
    tools = _FakeTools()
    executor = BoundedReActExecutor(llm=llm, tools=tools, events=_RecordingSink())
    request = _request(build_agent_budget(_settings()), system_prompt=skill_prompt)
    state = await _run(executor, request)

    assert llm.requests, "应至少发起一次 LLM 调用"
    first = llm.requests[0]
    messages = getattr(first, "messages", [])
    assert messages, "LLM 请求应包含消息"
    assert messages[0].role == "system"
    assert skill_prompt in messages[0].content, "技能包系统提示必须注入 ReAct 首条消息"
    assert state.outcome is not None
    assert state.outcome.outcome_type == PhaseExecutionOutcomeType.FINAL_PROPOSED
    assert state.outcome.answer == "报告完成"


# ---- 预算映射：settings → BudgetState ----
def test_build_agent_budget_maps_settings() -> None:
    settings = _settings()
    budget = build_agent_budget(settings)
    assert isinstance(budget, BudgetState)
    assert budget.limits.max_iterations == 12
    assert budget.limits.max_llm_calls == 15
    assert budget.limits.max_tool_calls == 18
    assert budget.limits.max_total_tokens == 50000
    assert budget.limits.max_input_tokens == 40000
    assert budget.limits.max_duration_seconds == 120.0
    assert budget.limits.max_repair_attempts == 1
    assert budget.limits.finalization_reserve_tokens == 2000


# ---- _outcome_answer 映射 ----
def test_outcome_answer_uses_final_answer_text() -> None:
    outcome = PhaseExecutionOutcome(
        outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
        answer="客户发现报告正文",
        reason_code="final_proposed",
    )
    assert _outcome_answer(outcome) == "客户发现报告正文"


def test_outcome_answer_serializes_candidate_output() -> None:
    outcome = PhaseExecutionOutcome(
        outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
        candidate_output={"score": 8, "rank": 1},
        reason_code="candidate_completed",
    )
    assert _outcome_answer(outcome) == '{"score": 8, "rank": 1}'


def test_outcome_answer_none_and_empty() -> None:
    assert _outcome_answer(None) == ""
    partial = PhaseExecutionOutcome(
        outcome_type=PhaseExecutionOutcomeType.PARTIAL_NO_PROGRESS,
        reason_code="no_progress",
    )
    assert _outcome_answer(partial) == ""


# ---- _history_summary 截断 ----
def test_history_summary_caps_messages_and_chars() -> None:
    from app.capabilities.llm.models import ChatMessage

    history = [ChatMessage(role="user", content=f"消息{i}") for i in range(20)]
    settings = SimpleNamespace(
        agent_context_summary_max_messages=3,
        agent_context_summary_max_chars=100,
    )
    summary = _history_summary(history, settings)  # type: ignore[arg-type]  # 测试注入缺省字段的 settings
    assert "消息17" in summary
    assert "消息0" not in summary  # 只保留最近 3 条


# ---- 核心修复：工具结果必须回写为 role="tool" 消息（防盲搜死循环）----
async def test_tool_results_fed_back_as_tool_messages() -> None:
    """工具执行结果必须以 role='tool' 消息进入下一轮 LLM 对话。

    回归防护：此前 executor 只把结果归一成 ObservationRecord，从不追加回
    state.messages，导致模型每轮只见悬空的 assistant tool_calls，永远得不到
    搜索结果反馈 → 无限循环调用 search_tools，正文始终为空。
    """

    def respond(call_index: int) -> list[SemanticChunk]:
        if call_index == 0:
            return _tool_call(
                "discover.client-finder.script.score_calculator",
                '{"input": "客户A"}',
                call_id="t1",
            )
        return _tool_call("submit_final_answer", '{"answer": "报告完成"}', call_id="t2")

    llm = _CapturingLLM(respond)
    tools = _FakeTools()
    executor = BoundedReActExecutor(llm=llm, tools=tools, events=_RecordingSink())
    request = _request(build_agent_budget(_settings()))
    state = await _run(executor, request)

    assert state.outcome is not None
    assert state.outcome.outcome_type == PhaseExecutionOutcomeType.FINAL_PROPOSED
    assert state.outcome.answer == "报告完成"
    assert len(llm.requests) >= 2, "应至少两轮 LLM 调用"
    second = llm.requests[1]
    messages = getattr(second, "messages", [])
    tool_msgs = [msg for msg in messages if msg.role == "tool"]
    assert tool_msgs, "工具结果必须以 role='tool' 消息回写进下一轮 LLM 对话"
    assert tool_msgs[0].tool_call_id == "t1"
    assert "数据" in tool_msgs[0].content


async def test_rejected_tool_call_still_gets_tool_response() -> None:
    """被 Policy 拒绝的调用也必须回写 tool 消息，保证 assistant tool_calls 不成对悬空。

    OpenAI 兼容协议要求每个 assistant tool_call 都有对应的 tool 回复；拒绝不能
    造成悬空 id，否则下一轮请求非法、模型无从得知该调用被拦下。
    """

    def respond(call_index: int) -> list[SemanticChunk]:
        if call_index == 0:
            return _tool_call(
                "discover.client-finder.script.score_calculator",
                '{"input": "客户A"}',
                call_id="t1",
            )
        return _tool_call("submit_final_answer", '{"answer": "报告完成"}', call_id="t2")

    llm = _CapturingLLM(respond)
    tools = _FakeTools()
    executor = BoundedReActExecutor(llm=llm, tools=tools, events=_RecordingSink())
    request = _request(build_agent_budget(_settings()))
    # allowed_tools 排除 score_calculator → 该调用被 Policy 拒绝
    request.allowed_tools = ["other.tool"]
    state = await _run(executor, request)

    assert state.outcome is not None
    assert state.outcome.outcome_type == PhaseExecutionOutcomeType.FINAL_PROPOSED
    assert len(llm.requests) >= 2, "拒绝后仍应进入下一轮 LLM 调用"
    second = llm.requests[1]
    messages = getattr(second, "messages", [])
    tool_msgs = [msg for msg in messages if msg.role == "tool"]
    assert tool_msgs, "被拒绝的调用也必须回写 role='tool' 消息"
    assert tool_msgs[0].tool_call_id == "t1"
    assert "白名单" in tool_msgs[0].content
