"""图运行时（L3）：节点实现 + 单轮执行入口（graph-runtime-spec §4）。

图只提供执行环境，业务流程在智能体清单正文。每个会话持有一个 Runtime
（内含会话级工具代理），跨轮保留 last_state 实现重入保护与历史累积。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from app.catalog.models import AssistantTarget, SelectionSource, TargetType
from app.config.loader import LLMProvider
from app.config.settings import Settings
from app.db.engine import Database
from app.errors.base import ConfigError, RegistryValidationError
from app.llm.client import LLMClient
from app.llm.models import (
    ChatMessage,
    ChatRequest,
    ChatToolCall,
    ChatToolCallFunction,
)
from app.llm.providers import ProviderRegistry
from app.llm.stream_parser import (
    PhaseSwitchChunk,
    TextChunk,
    ThinkingChunk,
    ToolCall,
    ToolCallsChunk,
    UsageChunk,
)
from app.llm.usage import UsageAggregator
from app.protocol.emitter import QueueEmitter
from app.protocol.events import (
    AgentEvent,
    AgentSelectedEvent,
    ArtifactReadyEvent,
    DoneEvent,
    GateCheckedEvent,
    SkillSelectedEvent,
    SourceDegradedEvent,
    ThinkingEndedEvent,
    ThinkingStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolsReadyEvent,
)
from app.protocol.sanitize import sanitize_tool_args, truncate
from app.registry.registry import AgentRegistry
from app.repositories.dedup import DedupStore
from app.runtime.builder import build_graph
from app.runtime.context import HistoryProvider, seed_for_turn, system_first, trim_context
from app.runtime.resolver.assistant_resolver import AssistantResolver, ExplicitSelectionResolver
from app.runtime.resolver.skill_resolver import SkillResolutionContext, SkillResolver
from app.runtime.state import GateStatus, GraphState
from app.schemas.files import ArtifactRecord
from app.services.files import FileService, file_preview_path
from app.services.workspace import WorkspaceManager
from app.tools.broker import ToolBroker, ToolCallRequest
from app.tools.mcp_manager import MCPManager
from app.tools.script_executor import ScriptExecutor

_GATE_MARKER = ".script.gate_"

logger = logging.getLogger(__name__)


def _parse_args(raw: str) -> dict[str, object]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _to_chat_tool_call(call: ToolCall) -> ChatToolCall:
    return ChatToolCall(
        id=call.id or "",
        function=ChatToolCallFunction(name=call.name or "", arguments=call.arguments),
    )


def _gate_id_from_tool(tool_name: str) -> str | None:
    if _GATE_MARKER not in tool_name:
        return None
    return tool_name.split(_GATE_MARKER, 1)[1]


class Runtime:
    """会话级图运行时：依赖持有 + 节点实现 + 单轮执行。"""

    def __init__(
        self,
        *,
        settings: Settings,
        workspaces: WorkspaceManager,
        files: FileService,
        registry: AgentRegistry,
        llm: LLMClient,
        providers: ProviderRegistry,
        resolve_api_key: Callable[[LLMProvider], str],
        mcp_manager: MCPManager,
        script_executor: ScriptExecutor,
        db: Database,
        history: HistoryProvider | None = None,
    ) -> None:
        self._settings = settings
        self._workspaces = workspaces
        self._files = files
        self._registry = registry
        self._llm = llm
        self._providers = providers
        self._api_key_resolver = resolve_api_key
        self._broker = ToolBroker(
            settings=settings,
            mcp_manager=mcp_manager,
            script_executor=script_executor,
            history_store=DedupStore(db),
        )
        self._assistant_resolver: AssistantResolver = ExplicitSelectionResolver()
        self._skill_resolver = SkillResolver()
        self._emitter: QueueEmitter | None = None
        self._assembled_skill: str | None = None
        self._last_state = GraphState()
        self._usage = UsageAggregator()
        self._graph: CompiledStateGraph[GraphState] | None = None
        self._turn_started = 0.0
        self._account_id: str = ""  # 会话归属账号（去重/产物登记据此隔离）
        self._history = history  # 会话记忆 L1：fresh runtime 首轮恢复历史上下文

    async def close(self) -> None:
        """会话结束：释放工具代理持有的 MCP 引用。"""
        await self._broker.close()

    # ---- 单轮执行入口 ----
    async def run_turn(
        self,
        *,
        session_id: str,
        user_input: str,
        emitter: QueueEmitter,
        account_id: str,
        assistant_target: AssistantTarget | None,
    ) -> GraphState:
        """执行一轮：沿用上轮状态，追加用户消息，跑图并落回 last_state。

        account_id / assistant_target 由路由从对话记录解析结果传入（不再读会话注册表）。
        """
        self._emitter = emitter
        self._turn_started = time.perf_counter()
        self._usage = UsageAggregator()  # 回合级 usage 归零（修复多调用覆盖）
        self._account_id = account_id
        user_message = ChatMessage(role="user", content=user_input)
        # 会话记忆 L1：fresh runtime 首轮从 DB 恢复历史上下文（best-effort 降级为空）
        seed = await seed_for_turn(
            self._last_state.messages,
            self._history,
            account_id=account_id,
            conversation_id=session_id,
            limit=self._settings.history_max_messages,
            user_message=user_message,
            logger=logger,
        )
        state = self._last_state.model_copy(
            update={
                "input": user_input,
                "session_id": session_id,
                "messages": seed,
                "assistant_target": assistant_target,
                "pending_calls": [],
                "turn": 0,  # 推理轮次按单条消息重置，避免会话内累积后永久短路
            }
        )
        if self._graph is None:
            self._graph = build_graph(self)
        final = await self._graph.ainvoke(state, config={"configurable": {"thread_id": session_id}})
        result_state = GraphState.model_validate(final)
        self._last_state = result_state
        return result_state

    def _emit_sync_guard(self) -> QueueEmitter:
        if self._emitter is None:
            raise RuntimeError("Runtime 尚未进入单轮执行")
        return self._emitter

    async def _emit(self, event: AgentEvent) -> None:
        if self._emitter is not None:
            await self._emitter.emit(event)

    # ---- 节点：一级解析（用户显式选择，非 LLM 路由） ----
    async def resolve_assistant(self, state: GraphState) -> dict[str, object]:
        """解析助手：读本回合对话记录绑定（graph-runtime-spec §4/§8）。

        绑定变更（含首次）→ 清旧装配快照、重发选定事件；绑定沿用 → 直接跳过。
        """
        target = self._assistant_resolver.resolve(state.assistant_target)
        if state.active_target is not None and state.active_target == target:
            return {"resolve_reason": "沿用已装配助手"}
        # 绑定变更：清装配快照，确保 assemble 按新目标重建
        self._assembled_skill = None
        if target is None or target.type == TargetType.GENERIC:
            return {"active_target": target, "active_skill": None, "resolve_reason": "通用对话"}
        agent = self._registry.index().agents.get(target.id or "")
        if agent is None:
            return {
                "active_target": None,
                "active_skill": None,
                "resolve_reason": "绑定的专家不可用",
            }
        await self._emit(
            AgentSelectedEvent(
                agent_id=target.id or "",
                display_name=agent.display_name,
                reason="用户显式选择",
                confidence=1.0,
                source=SelectionSource.USER,
            )
        )
        return {"active_target": target, "active_skill": None, "resolve_reason": "用户显式选择"}

    # ---- 节点：二级解析（确定性技能解析） ----
    async def resolve_skill(self, state: GraphState) -> dict[str, object]:
        """解析技能：SkillResolver 策略链（显式 → 默认 → 唯一 → 首个）。"""
        if state.active_target is None or state.active_target.type != TargetType.EXPERT:
            return {"resolve_reason": "无专家助手"}
        if state.active_skill:
            return {"resolve_reason": "沿用已装配技能"}
        package = self._registry.get_agent(state.active_target.id or "")
        skill_ids = tuple(package.skills.keys()) if package is not None else ()
        if not skill_ids:
            return {"active_skill": None, "resolve_reason": "该专家无可用技能"}
        context = SkillResolutionContext(
            skill_ids=skill_ids,
            default_skill=package.manifest.default_skill if package is not None else None,
            explicit_skill=None,  # 显式技能选择为未来能力（对话记录 skill 字段）
        )
        skill_id = self._skill_resolver.resolve(context)
        if skill_id is None:
            return {"active_skill": None, "resolve_reason": "技能解析失败"}
        await self._emit(SkillSelectedEvent(skill_id=skill_id, reason="确定性解析"))
        return {"active_skill": skill_id, "resolve_reason": "确定性解析"}

    # ---- 节点：装配 ----
    async def assemble(self, state: GraphState) -> dict[str, object]:
        """装配：注入系统上下文 + 激活工具代理（§4）。"""
        if state.active_target is None or state.active_skill is None:
            raise ConfigError("缺少智能体或技能，无法装配")
        if self._assembled_skill == state.active_skill:
            return {}
        agent_id = state.active_target.id or ""
        package = self._registry.get_agent(agent_id)
        if package is None:
            raise RegistryValidationError(f"未知智能体：{agent_id}")
        plan = self._registry.assemble(agent_id, state.active_skill)
        skill_dir = package.root / state.active_skill
        workspace = await self._workspaces.create(agent_id)
        activation = await self._broker.activate(
            plan=plan,
            skill_dir=skill_dir,
            workspace=workspace.root,
            session_id=state.session_id,
            account_id=self._account_id,
        )
        self._assembled_skill = state.active_skill
        if not activation.ok:
            raise ConfigError(f"必需 MCP 依赖不可用：{', '.join(activation.failed_required)}")
        degraded: list[str] = []
        for server_id, note in zip(
            activation.degraded_services, activation.degrade_notes, strict=True
        ):
            degraded.append(server_id)
            await self._emit(
                SourceDegradedEvent(source=server_id, reason="服务不可用", degrade_note=note)
            )
        await self._emit(
            ToolsReadyEvent(
                core_count=activation.core_count,
                catalog_size=activation.catalog_size,
                started_services=activation.started_services,
            )
        )
        system_message = ChatMessage(role="system", content=plan.system_prompt)
        return {
            "messages": [system_message],
            "workspace_path": str(workspace.root),
            "exposed_tools": [spec.function.name for spec in self._broker.exposed_tools()],
            "degraded_sources": degraded,
        }

    # ---- 节点：推理 ----
    async def agent(self, state: GraphState) -> dict[str, object]:
        """推理循环节点：思考/正文分流出、工具调用累积、轮次上限。"""
        turn = state.turn + 1
        at_limit = turn >= self._settings.reasoning_max_turns
        provider = self._resolve_provider(state)
        api_key = self._resolve_api_key(provider)
        request = ChatRequest(
            messages=trim_context(
                system_first(state.messages), self._settings.context_budget_tokens
            ),
            tools=self._broker.exposed_tools(),
            thinking=self._resolve_thinking(state),
        )
        text_parts: list[str] = []
        pending: list[ToolCallRequest] = []
        tool_calls_accum: list[ToolCall] = []
        thinking_open = False
        start = time.perf_counter()
        chunk_count = 0
        logger.info(
            "LLM 流式调用开始",
            extra={
                "provider": provider.id,
                "model": provider.model,
                "turn": turn,
                "messages": len(request.messages),
                "tools": len(request.tools or []),
            },
        )
        async for chunk in self._llm.stream_chat(
            provider=provider, api_key=api_key, request=request
        ):
            chunk_count += 1
            if isinstance(chunk, ThinkingChunk):
                if not thinking_open:
                    await self._emit(ThinkingStartedEvent())
                    thinking_open = True
                self._emit_sync_guard().thinking_delta(chunk.text)
            elif isinstance(chunk, PhaseSwitchChunk):
                if chunk.to != "thinking" and thinking_open:
                    await self._emit(
                        ThinkingEndedEvent(duration_ms=int((time.perf_counter() - start) * 1000))
                    )
                    thinking_open = False
            elif isinstance(chunk, TextChunk):
                self._emit_sync_guard().text_delta(chunk.text)
                text_parts.append(chunk.text)
            elif isinstance(chunk, ToolCallsChunk):
                tool_calls_accum = chunk.tool_calls
                pending = [
                    ToolCallRequest(
                        call_id=c.id or "",
                        tool_name=c.name or "",
                        arguments=_parse_args(c.arguments),
                    )
                    for c in chunk.tool_calls
                ]
            elif isinstance(chunk, UsageChunk):
                self._usage.add(chunk)
        logger.info(
            "LLM 流式调用结束",
            extra={
                "provider": provider.id,
                "model": provider.model,
                "turn": turn,
                "chunk_count": chunk_count,
                "duration_ms": int((time.perf_counter() - start) * 1000),
                "text_len": len("".join(text_parts)),
                "tool_calls": len(tool_calls_accum),
                "thinking_open": thinking_open,
            },
        )
        if thinking_open:
            await self._emit(
                ThinkingEndedEvent(duration_ms=int((time.perf_counter() - start) * 1000))
            )
        if at_limit:
            return {
                "turn": turn,
                "messages": [
                    ChatMessage(role="system", content="已达轮次上限，请基于现有信息给出结论")
                ],
                # 清空待执行工具调用，保证 agent ⇄ tool_node 循环终止，
                # 否则上轮遗留的 pending_calls 会让条件边再次进入 tool_node 死循环
                "pending_calls": [],
            }
        text = "".join(text_parts)
        assistant = ChatMessage(
            role="assistant",
            content=text or None,
            tool_calls=[_to_chat_tool_call(c) for c in tool_calls_accum] or None,
        )
        return {"turn": turn, "messages": [assistant], "pending_calls": pending}

    # ---- 节点：工具执行 ----
    async def tool_node(self, state: GraphState) -> dict[str, object]:
        """工具执行节点：分发、事件、门禁、产物登记（§4）。"""
        calls = state.pending_calls
        for call in calls:
            summary = sanitize_tool_args(
                json.dumps(call.arguments, ensure_ascii=False), max_length=200
            )
            await self._emit(
                ToolCallStartedEvent(
                    call_id=call.call_id, tool_name=call.tool_name, args_summary=summary
                )
            )
        results = await self._broker.execute(calls)
        tool_messages: list[ChatMessage] = []
        gate_updates: dict[str, GateStatus] = {}
        artifacts: list[ArtifactRecord] = []
        workspace = Path(state.workspace_path)
        for result in results:
            await self._emit(
                ToolCallCompletedEvent(
                    call_id=result.call_id,
                    ok=result.ok,
                    result_summary=truncate(result.content or result.message, max_length=300),
                    duration_ms=result.duration_ms,
                    truncated=result.truncated,
                )
            )
            tool_messages.append(
                ChatMessage(
                    role="tool",
                    content=result.content or result.message,
                    tool_call_id=result.call_id,
                )
            )
            gate_id = _gate_id_from_tool(result.tool_name)
            if gate_id is not None:
                failures = [] if result.ok else [result.message]
                gate_updates[gate_id] = GateStatus(
                    passed=result.ok, failures=failures, turn=state.turn
                )
                await self._emit(
                    GateCheckedEvent(gate_id=gate_id, passed=result.ok, failures=failures)
                )
            for rel in result.produced_files:
                record = await self._files.register(
                    created_by=self._account_id,
                    source_path=workspace / rel,
                    filename=Path(rel).name,
                )
                await self._emit(
                    ArtifactReadyEvent(
                        artifact_id=record.artifact_id,
                        filename=record.filename,
                        media_type=record.media_type,
                        size_bytes=record.size_bytes,
                        download_url=file_preview_path(record),
                    )
                )
                artifacts.append(record)
        return {
            "messages": tool_messages,
            "gate_status": gate_updates,
            "artifacts": artifacts,
        }

    # ---- 节点：通用对话 ----
    async def generic_chat(self, state: GraphState) -> dict[str, object]:
        """无智能体命中时的兜底（graph-runtime-spec §4）。"""
        provider = self._providers.resolve(self._settings.default_provider_id)
        api_key = self._resolve_api_key(provider)
        index = self._registry.index()
        # 只暴露 display_name：模型正文不得回显内部 agent_id（页面统一用展示名）
        agents_text = "\n".join(
            f"- {a.display_name}：{a.description}" for a in index.agents.values()
        )
        system = (
            "你是多智能体平台助手。以下专家可用：\n"
            f"{agents_text or '（暂无）'}\n"
            "若用户需求匹配某个专家，请提示用户在上方助手列表中选择后使用。"
        )
        request = ChatRequest(
            messages=[ChatMessage(role="system", content=system), *state.messages],
            thinking=self._settings.thinking_enabled,
        )
        text_parts: list[str] = []
        thinking_open = False
        start = time.perf_counter()
        async for chunk in self._llm.stream_chat(
            provider=provider, api_key=api_key, request=request
        ):
            if isinstance(chunk, ThinkingChunk):
                if not thinking_open:
                    await self._emit(ThinkingStartedEvent())
                    thinking_open = True
                self._emit_sync_guard().thinking_delta(chunk.text)
            elif isinstance(chunk, PhaseSwitchChunk):
                if chunk.to != "thinking" and thinking_open:
                    await self._emit(
                        ThinkingEndedEvent(duration_ms=int((time.perf_counter() - start) * 1000))
                    )
                    thinking_open = False
            elif isinstance(chunk, TextChunk):
                self._emit_sync_guard().text_delta(chunk.text)
                text_parts.append(chunk.text)
            elif isinstance(chunk, UsageChunk):
                self._usage.add(chunk)
        if thinking_open:
            await self._emit(
                ThinkingEndedEvent(duration_ms=int((time.perf_counter() - start) * 1000))
            )
        assistant = ChatMessage(role="assistant", content="".join(text_parts))
        return {"messages": [assistant]}

    # ---- 节点：收尾 ----
    async def finish(self, state: GraphState) -> dict[str, object]:
        provider = self._resolve_provider(state)
        await self._emit(
            DoneEvent(
                turns=state.turn,
                duration_ms=int((time.perf_counter() - self._turn_started) * 1000),
                usage=self._usage.snapshot(),
                provider=provider.id,
                model=provider.model,
            )
        )
        return {}

    def _resolve_provider(self, state: GraphState) -> LLMProvider:
        preference: str | None = None
        if state.active_target is not None and state.active_target.type == TargetType.EXPERT:
            package = self._registry.get_agent(state.active_target.id or "")
            if package is not None and package.manifest.model_preference:
                preference = package.manifest.model_preference
        provider_id = preference or self._settings.default_provider_id
        return self._providers.resolve(provider_id)

    def _resolve_thinking(self, state: GraphState) -> bool:
        if not self._settings.thinking_enabled:
            return False
        if state.active_target is not None and state.active_target.type == TargetType.EXPERT:
            package = self._registry.get_agent(state.active_target.id or "")
            if package is not None and package.manifest.thinking_preference == "off":
                return False
        return True

    def _resolve_api_key(self, provider: LLMProvider) -> str:
        return self._api_key_resolver(provider)
