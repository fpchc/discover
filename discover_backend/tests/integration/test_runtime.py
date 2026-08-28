"""Step 8 图运行时测试。"""

import json
from pathlib import Path

import anyio
from app.catalog.models import AssistantTarget, TargetType
from app.config.loader import LLMProvider, LLMRegistry, MCPRegistry, MCPServer
from app.config.settings import Settings
from app.db.engine import Database
from app.extensions.storage.local_storage import LocalStorage
from app.llm.providers import ProviderRegistry
from app.llm.stream_parser import (
    FinishChunk,
    PhaseSwitchChunk,
    TextChunk,
    ToolCall,
    ToolCallsChunk,
)
from app.protocol.emitter import QueueEmitter
from app.protocol.events import (
    AgentEvent,
    AgentSelectedEvent,
    DoneEvent,
    SkillSelectedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolsReadyEvent,
)
from app.registry.registry import AgentRegistry
from app.runtime.builder import route_from_resolve_assistant
from app.runtime.runner import Runtime
from app.runtime.state import GraphState
from app.session.service import SessionService
from app.tools.mcp_client import MCPCallResult, MCPToolInfo
from app.tools.script_executor import ScriptExecution

AGENT_MD = """\
---
agent_id: finder
display_name: 客户发现
version: 1.0.0
description: 发现潜在客户
scope:
  applies: 用户想找潜在客户时
  does_not_apply: 用户想写周报时
default_skill: research
env_whitelist: []
skills:
  - research
---
全局约束：语气专业，只讲事实。
"""

SKILL_MD = """\
---
skill_id: research
version: 1.0.0
description: 客户调研
scope:
  applies: 需要调研时
  does_not_apply: 纯闲聊
mcp_dependencies:
  - server: alibaba_search
    required: true
scripts:
  - path: scripts/run.py
    name: run
    description: 执行调研脚本
---
完整工作流：先收集信源，再撰写报告。
"""

SKILL_MD_DELETE = """\
---
skill_id: research
version: 1.0.0
description: 客户调研
scope:
  applies: 需要调研时
  does_not_apply: 纯闲聊
mcp_dependencies:
  - server: alibaba_search
    required: true
scripts:
  - path: scripts/run.py
    name: run
    description: 删除临时文件
    side_effect: delete
---
完整工作流：先收集信源，再撰写报告。
"""


def _write_agent(root: Path, skill_md: str = SKILL_MD) -> None:
    agent_dir = root / "finder"
    (agent_dir / "research" / "scripts").mkdir(parents=True)
    (agent_dir / "research" / "references").mkdir(parents=True)
    (agent_dir / "AGENT.md").write_text(AGENT_MD, encoding="utf-8")
    (agent_dir / "research" / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (agent_dir / "research" / "scripts" / "run.py").write_text("print('ok')", encoding="utf-8")
    (agent_dir / "research" / "references" / "guide.md").write_text("# 指南\n", encoding="utf-8")


class FakeLLM:
    """脚本化 LLM：推理返回文本或工具调用（无 LLM 路由分支）。"""

    def __init__(
        self,
        *,
        reason_text: str = "你好",
        tool_call: tuple[str, dict[str, object]] | None = None,
        always_tool: bool = False,
    ) -> None:
        self._reason_text = reason_text
        self._tool_call = tool_call
        self._always_tool = always_tool
        self.reason_calls = 0

    async def stream_chat(self, *, provider: LLMProvider, api_key: str, request: object) -> object:
        del provider, api_key
        self.reason_calls += 1
        if self._always_tool:
            yield ToolCallsChunk(
                tool_calls=[
                    ToolCall(
                        index=0,
                        id="t1",
                        name="finder.research.script.run",
                        arguments="{}",
                    )
                ]
            )
            yield FinishChunk(reason="tool_calls")
            return
        if self._tool_call is not None:
            name, args_dict = self._tool_call
            self._tool_call = None
            yield ToolCallsChunk(
                tool_calls=[ToolCall(index=0, id="t1", name=name, arguments=json.dumps(args_dict))]
            )
            yield FinishChunk(reason="tool_calls")
            return
        yield PhaseSwitchChunk(to="text")
        yield TextChunk(text=self._reason_text)
        yield FinishChunk(reason="stop")


class _FakeClient:
    call_timeout_seconds = 30.0

    async def list_tools(self) -> list[MCPToolInfo]:
        return [
            MCPToolInfo(name="web_search", description="网页搜索", input_schema={"type": "object"})
        ]

    async def call_tool(self, name: str, arguments: dict[str, object]) -> MCPCallResult:
        del name, arguments
        return MCPCallResult(content="搜索结果")


class _FakeMCPManager:
    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.released: list[str] = []

    async def acquire(self, server_id: str) -> _FakeClient:
        self.acquired.append(server_id)
        return _FakeClient()

    def release(self, server_id: str) -> None:
        self.released.append(server_id)

    def concurrency_limit(self, server_id: str) -> int:
        del server_id
        return 2


class _FakeScriptExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run(self, **kwargs: object) -> ScriptExecution:
        self.calls.append(kwargs)
        return ScriptExecution(exit_code=0, stdout="脚本结果")


def _provider() -> LLMProvider:
    return LLMProvider(
        id="qwen-max",
        display_name="Qwen",
        base_url="https://llm.example.com/v1",
        api_key_env="LLM_API_KEY",
        model="qwen-max",
        supports_thinking=True,
        thinking_field="reasoning_content",
        context_window=131072,
    )


def _mcp_registry() -> MCPRegistry:
    return MCPRegistry(
        servers=[
            MCPServer(
                id="alibaba_search",
                transport="streamable_http",
                base_url="https://mcp.example.com",
            )
        ]
    )


_DATABASE = Database(Settings(_env_file=None))


async def _runtime(
    tmp_path: Path,
    *,
    fake_llm: FakeLLM,
    skill_md: str = SKILL_MD,
    max_turns: int = 40,
    bind: bool = True,
) -> tuple[Runtime, SessionService, _FakeScriptExecutor, str]:
    _write_agent(tmp_path, skill_md=skill_md)
    settings = Settings(
        _env_file=None,
        agents_root_dir=tmp_path,
        agent_workspace_root_dir=tmp_path / "workspaces",
        storage_root_dir=tmp_path / "storage",
        tool_log_root_dir=tmp_path / "logs",
        hot_reload_enabled=False,
        reasoning_max_turns=max_turns,
        # 显式指定 provider：fake 注册表只注册了 qwen-max（见 _provider），
        # 而 Settings 默认值是 qwen3.7-max，不固定会解析失败。
        default_provider_id="qwen-max",
    )
    sessions = SessionService(settings, _DATABASE, LocalStorage(tmp_path / "storage"))
    record = await sessions.create_session("00000000-0000-0000-0000-0000000000cc")
    if bind:
        sessions.bind_assistant(
            record.session_id, AssistantTarget(type=TargetType.EXPERT, id="finder")
        )
    registry = AgentRegistry(settings, _mcp_registry())
    await registry.refresh()
    providers = ProviderRegistry(LLMRegistry(providers=[_provider()]))
    fake_script = _FakeScriptExecutor()
    runtime = Runtime(
        settings=settings,
        sessions=sessions,
        registry=registry,
        llm=fake_llm,
        providers=providers,
        resolve_api_key=lambda _provider: "k",
        mcp_manager=_FakeMCPManager(),
        script_executor=fake_script,
        db=_DATABASE,
    )
    return runtime, sessions, fake_script, record.session_id


async def _collect(emitter: QueueEmitter) -> list[AgentEvent]:
    await emitter.finish()
    events: list[AgentEvent] = []
    while True:
        try:
            with anyio.fail_after(0.05):
                events.append(await emitter.get())
        except TimeoutError:
            break
    return events


# ---- 解析辅助 ----
def test_route_from_resolve_assistant() -> None:
    expert = AssistantTarget(type=TargetType.EXPERT, id="finder")
    assert route_from_resolve_assistant(GraphState(active_target=expert)) == "resolve_skill"
    assert route_from_resolve_assistant(GraphState()) == "generic_chat"
    generic = AssistantTarget(type=TargetType.GENERIC)
    assert route_from_resolve_assistant(GraphState(active_target=generic)) == "generic_chat"


# ---- 端到端：解析 + 装配 + 推理 ----
async def test_run_turn_resolves_bound_assistant(tmp_path: Path) -> None:
    fake_llm = FakeLLM()
    runtime, _sessions, _script, session_id = await _runtime(tmp_path, fake_llm=fake_llm)
    emitter = QueueEmitter(Settings(_env_file=None))
    final = await runtime.run_turn(session_id=session_id, user_input="帮我找客户", emitter=emitter)
    events = await _collect(emitter)
    assert final.active_target == AssistantTarget(type=TargetType.EXPERT, id="finder")
    assert final.active_skill == "research"
    assert final.turn >= 1
    assert any(isinstance(e, AgentSelectedEvent) for e in events)
    assert any(isinstance(e, SkillSelectedEvent) for e in events)
    assert any(isinstance(e, ToolsReadyEvent) for e in events)
    assert any(isinstance(e, DoneEvent) for e in events)
    assert any(m.role == "assistant" and "你好" in (m.content or "") for m in final.messages)


async def test_binding_persists_across_turns(tmp_path: Path) -> None:
    fake_llm = FakeLLM()
    runtime, _sessions, _script, session_id = await _runtime(tmp_path, fake_llm=fake_llm)
    first_emitter = QueueEmitter(Settings(_env_file=None))
    await runtime.run_turn(session_id=session_id, user_input="帮我找客户", emitter=first_emitter)
    first_events = await _collect(first_emitter)
    selected_count = sum(isinstance(e, AgentSelectedEvent) for e in first_events)
    reason_after_first = fake_llm.reason_calls
    second_emitter = QueueEmitter(Settings(_env_file=None))
    final = await runtime.run_turn(session_id=session_id, user_input="继续", emitter=second_emitter)
    second_events = await _collect(second_emitter)
    # 第二轮沿用绑定：不再发 AgentSelectedEvent、不重复装配，仅推理
    assert sum(isinstance(e, AgentSelectedEvent) for e in second_events) == 0
    assert fake_llm.reason_calls == reason_after_first + 1
    assert selected_count == 1
    assert final.active_target == AssistantTarget(type=TargetType.EXPERT, id="finder")
    assert final.active_skill == "research"


async def test_unbound_goes_generic_chat(tmp_path: Path) -> None:
    fake_llm = FakeLLM()
    runtime, _sessions, _script, session_id = await _runtime(
        tmp_path, fake_llm=fake_llm, bind=False
    )
    emitter = QueueEmitter(Settings(_env_file=None))
    final = await runtime.run_turn(session_id=session_id, user_input="随便聊聊", emitter=emitter)
    events = await _collect(emitter)
    assert final.active_target is None
    assert any(m.role == "assistant" and "你好" in (m.content or "") for m in final.messages)
    assert not any(isinstance(e, AgentSelectedEvent) for e in events)


async def test_switch_target_reassembles(tmp_path: Path) -> None:
    fake_llm = FakeLLM()
    runtime, sessions, _script, session_id = await _runtime(tmp_path, fake_llm=fake_llm)
    first_emitter = QueueEmitter(Settings(_env_file=None))
    first = await runtime.run_turn(
        session_id=session_id, user_input="帮我找客户", emitter=first_emitter
    )
    await _collect(first_emitter)
    assert first.active_target == AssistantTarget(type=TargetType.EXPERT, id="finder")
    # 切换为通用对话
    sessions.bind_assistant(session_id, AssistantTarget(type=TargetType.GENERIC))
    second_emitter = QueueEmitter(Settings(_env_file=None))
    second = await runtime.run_turn(
        session_id=session_id, user_input="随便聊聊", emitter=second_emitter
    )
    second_events = await _collect(second_emitter)
    assert second.active_target == AssistantTarget(type=TargetType.GENERIC)
    assert second.active_skill is None
    assert not any(isinstance(e, AgentSelectedEvent) for e in second_events)
    # 切回专家：重装配
    sessions.bind_assistant(session_id, AssistantTarget(type=TargetType.EXPERT, id="finder"))
    third_emitter = QueueEmitter(Settings(_env_file=None))
    third = await runtime.run_turn(
        session_id=session_id, user_input="帮我找客户", emitter=third_emitter
    )
    third_events = await _collect(third_emitter)
    assert third.active_target == AssistantTarget(type=TargetType.EXPERT, id="finder")
    assert third.active_skill == "research"
    assert any(isinstance(e, AgentSelectedEvent) for e in third_events)


# ---- 工具流 ----
async def test_tool_execution_flow(tmp_path: Path) -> None:
    fake_llm = FakeLLM(tool_call=("finder.research.script.run", {"input": "调研"}))
    runtime, _sessions, fake_script, session_id = await _runtime(tmp_path, fake_llm=fake_llm)
    emitter = QueueEmitter(Settings(_env_file=None))
    final = await runtime.run_turn(session_id=session_id, user_input="执行调研", emitter=emitter)
    events = await _collect(emitter)
    assert fake_script.calls  # 脚本已执行
    assert any(isinstance(e, ToolCallStartedEvent) for e in events)
    assert any(isinstance(e, ToolCallCompletedEvent) for e in events)
    assert any(m.role == "tool" and "脚本结果" in (m.content or "") for m in final.messages)


# ---- 轮次重置与会话解焊回归（修复 A+B） ----
async def test_turn_resets_between_messages(tmp_path: Path) -> None:
    """修复 A：推理轮次按单条消息重置，不跨消息累积。"""
    fake_llm = FakeLLM(tool_call=("finder.research.script.run", {"input": "x"}))
    runtime, _sessions, _script, session_id = await _runtime(tmp_path, fake_llm=fake_llm)
    # 第一轮含一次工具调用：agent(turn1,tool) → tool → agent(turn2,text) → finish
    first_emitter = QueueEmitter(Settings(_env_file=None))
    final1 = await runtime.run_turn(
        session_id=session_id, user_input="执行调研", emitter=first_emitter
    )
    await _collect(first_emitter)
    assert final1.turn == 2
    # 第二轮纯文本：应重置为 0 起算（修复前会从 2 续增得到 turn=3）
    second_emitter = QueueEmitter(Settings(_env_file=None))
    final2 = await runtime.run_turn(
        session_id=session_id, user_input="继续", emitter=second_emitter
    )
    await _collect(second_emitter)
    assert final2.turn == 1


async def test_capped_turn_then_next_message_not_bricked(tmp_path: Path) -> None:
    """修复 A+B 组合：触顶后下一条消息不再被永久短路，能继续推理。"""
    fake_llm = FakeLLM(always_tool=True)
    runtime, _sessions, _script, session_id = await _runtime(
        tmp_path, fake_llm=fake_llm, max_turns=2
    )
    first_emitter = QueueEmitter(Settings(_env_file=None))
    final1 = await runtime.run_turn(
        session_id=session_id, user_input="搜索客户", emitter=first_emitter
    )
    await _collect(first_emitter)
    assert final1.turn == 2
    assert any(m.role == "system" and "已达轮次上限" in (m.content or "") for m in final1.messages)
    calls_after_cap = fake_llm.reason_calls
    # 下一条消息切换为普通回复，验证仍会调用 LLM（修复前此处直接短路，不再调用）
    fake_llm._always_tool = False
    second_emitter = QueueEmitter(Settings(_env_file=None))
    final2 = await runtime.run_turn(
        session_id=session_id, user_input="继续", emitter=second_emitter
    )
    await _collect(second_emitter)
    assert fake_llm.reason_calls == calls_after_cap + 1  # 未被短路，正常推理
    assert final2.turn == 1
    assert any(m.role == "assistant" and "你好" in (m.content or "") for m in final2.messages)


# ---- 副作用工具（审批已移除，直接执行） ----
async def test_side_effect_tool_runs_without_approval(tmp_path: Path) -> None:
    fake_llm = FakeLLM(tool_call=("finder.research.script.run", {}))
    runtime, _sessions, fake_script, session_id = await _runtime(
        tmp_path, fake_llm=fake_llm, skill_md=SKILL_MD_DELETE
    )
    emitter = QueueEmitter(Settings(_env_file=None))
    final = await runtime.run_turn(session_id=session_id, user_input="删除数据", emitter=emitter)
    events = await _collect(emitter)
    assert fake_script.calls  # 删除副作用不再挂起审批，直接执行
    assert any(isinstance(e, DoneEvent) for e in events)
    assert any(m.role == "tool" and "脚本结果" in (m.content or "") for m in final.messages)
