"""图运行时（L3）：节点实现 + 单轮执行入口（graph-runtime-spec §4）。

图只提供执行环境，业务流程在智能体清单正文。每个会话持有一个 Runtime
（内含会话级工具代理），跨轮保留 last_state 实现重入保护与历史累积。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from app.config.loader import LLMProvider
from app.config.settings import Settings
from app.db.engine import Database
from app.errors.base import ConfigError, RegistryValidationError
from app.history.repo import HistoryStore
from app.llm.client import LLMClient
from app.llm.models import (
    ChatMessage,
    ChatRequest,
    ChatToolCall,
    ChatToolCallFunction,
    ChatToolSpec,
    ToolFunction,
)
from app.llm.providers import ProviderRegistry
from app.llm.stream_parser import (
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
from app.runtime.builder import build_graph
from app.runtime.state import GateStatus, GraphState, RouteDecision
from app.session.models import ArtifactRecord
from app.session.service import (
    SessionService,
    file_preview_path,
)
from app.tools.broker import ToolBroker, ToolCallRequest
from app.tools.mcp_manager import MCPManager
from app.tools.script_executor import ScriptExecutor

_ROUTE_AGENT_TOOL = ChatToolSpec(
    function=ToolFunction(
        name="select_agent",
        description="从候选智能体中选择最匹配的一个；若无匹配，agent_id 填空字符串",
        parameters={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "confidence": {"type": "number", "description": "0~1 的匹配置信度"},
                "reason": {"type": "string"},
            },
            "required": ["agent_id", "confidence", "reason"],
        },
    )
)

_ROUTE_SKILL_TOOL = ChatToolSpec(
    function=ToolFunction(
        name="select_skill",
        description="从候选技能中选择最匹配的一个",
        parameters={
            "type": "object",
            "properties": {
                "skill_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["skill_id", "reason"],
        },
    )
)

_SWITCH_KEYWORDS = ("切换智能体", "换个智能体", "换一个智能体", "切换到其他")
_GATE_MARKER = ".script.gate_"


def _wants_switch(text: str) -> bool:
    return any(keyword in text for keyword in _SWITCH_KEYWORDS)


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


def _estimate_tokens(messages: list[ChatMessage]) -> int:
    """粗略 token 估算：以字符数为代理（CJK 近似 1 token/字符）。"""
    return sum(len(message.content or "") for message in messages)


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
        sessions: SessionService,
        registry: AgentRegistry,
        llm: LLMClient,
        providers: ProviderRegistry,
        resolve_api_key: Callable[[LLMProvider], str],
        mcp_manager: MCPManager,
        script_executor: ScriptExecutor,
        db: Database,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self._registry = registry
        self._llm = llm
        self._providers = providers
        self._api_key_resolver = resolve_api_key
        self._broker = ToolBroker(
            settings=settings,
            mcp_manager=mcp_manager,
            script_executor=script_executor,
            history_store=HistoryStore(db),
        )
        self._emitter: QueueEmitter | None = None
        self._assembled_skill: str | None = None
        self._last_state = GraphState()
        self._usage = UsageAggregator()
        self._graph: CompiledStateGraph[GraphState] | None = None
        self._turn_started = 0.0

    async def close(self) -> None:
        """会话结束：释放工具代理持有的 MCP 引用。"""
        await self._broker.close()

    # ---- 单轮执行入口 ----
    async def run_turn(
        self, *, session_id: str, user_input: str, emitter: QueueEmitter
    ) -> GraphState:
        """执行一轮：沿用上轮状态，追加用户消息，跑图并落回 last_state。"""
        self._emitter = emitter
        self._turn_started = time.perf_counter()
        self._usage = UsageAggregator()  # 回合级 usage 归零（修复多调用覆盖）
        user_message = ChatMessage(role="user", content=user_input)
        base = self._last_state
        state = base.model_copy(
            update={
                "input": user_input,
                "session_id": session_id,
                "messages": [*base.messages, user_message],
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

    # ---- 节点：一级路由 ----
    async def route_agent(self, state: GraphState) -> dict[str, object]:
        """一级路由（graph-runtime-spec §9 重入保护）。"""
        if state.active_agent and not _wants_switch(state.input):
            return {"route_reason": "沿用已装配智能体"}
        index = self._registry.index()
        candidates = list(index.agents.values())
        if not candidates:
            return {"active_agent": None, "route_reason": "平台暂无可用智能体"}
        decision = await self._route_llm(
            candidates_text="\n".join(
                f"- {a.agent_id}（{a.display_name}）：{a.description}，适用：{a.scope.applies}"
                for a in candidates
            ),
            user_input=state.input,
            tool=_ROUTE_AGENT_TOOL,
            target_key="agent_id",
            instruction="从候选智能体中选出与用户需求最匹配的一个，返回其 agent_id、置信度与理由。",
        )
        if decision is None or decision.confidence < self._settings.routing_confidence_threshold:
            return {"active_agent": None, "route_reason": "未匹配到可用智能体"}
        agent = index.agents.get(decision.target)
        if agent is None:
            return {"active_agent": None, "route_reason": "未匹配到可用智能体"}
        self._sessions.bind_agent(state.session_id, agent.agent_id)
        await self._emit(
            AgentSelectedEvent(
                agent_id=agent.agent_id,
                display_name=agent.display_name,
                reason=decision.reason,
                confidence=decision.confidence,
            )
        )
        return {"active_agent": agent.agent_id, "route_reason": decision.reason}

    # ---- 节点：二级路由 ----
    async def route_skill(self, state: GraphState) -> dict[str, object]:
        """二级路由：在选定智能体内选技能，可切换。"""
        if not state.active_agent:
            return {"route_reason": "无智能体"}
        index = self._registry.index()
        skills = index.skills_by_agent.get(state.active_agent, {})
        if not skills:
            return {"active_skill": None, "route_reason": "该智能体无可用技能"}
        if state.active_skill and not _wants_switch(state.input):
            return {"route_reason": "沿用已装配技能"}
        decision = await self._route_llm(
            candidates_text="\n".join(
                f"- {s.skill_id}：{s.description}，适用：{s.scope.applies}" for s in skills.values()
            ),
            user_input=state.input,
            tool=_ROUTE_SKILL_TOOL,
            target_key="skill_id",
            instruction="从候选技能中选出与用户需求最匹配的一个，返回其 skill_id 与理由。",
        )
        skill_id: str | None = decision.target if decision else None
        reason = decision.reason if decision else ""
        if skill_id is None or skill_id not in skills:
            package = self._registry.get_agent(state.active_agent)
            if package is not None and package.manifest.default_skill:
                skill_id = package.manifest.default_skill
                reason = "使用默认技能"
        if skill_id is None or skill_id not in skills:
            skill_id = next(iter(skills))
            reason = "使用首个可用技能"
        await self._emit(SkillSelectedEvent(skill_id=skill_id, reason=reason))
        return {"active_skill": skill_id, "route_reason": reason}

    # ---- 节点：装配 ----
    async def assemble(self, state: GraphState) -> dict[str, object]:
        """装配：注入系统上下文 + 激活工具代理（§4）。"""
        if state.active_agent is None or state.active_skill is None:
            raise ConfigError("缺少智能体或技能，无法装配")
        if self._assembled_skill == state.active_skill:
            return {}
        package = self._registry.get_agent(state.active_agent)
        if package is None:
            raise RegistryValidationError(f"未知智能体：{state.active_agent}")
        plan = self._registry.assemble(state.active_agent, state.active_skill)
        skill_dir = package.root / state.active_skill
        workspace = await self._sessions.workspace_for(state.active_agent)
        activation = await self._broker.activate(
            plan=plan,
            skill_dir=skill_dir,
            workspace=workspace.root,
            session_id=state.session_id,
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
            messages=self._trim_context(state.messages),
            tools=self._broker.exposed_tools(),
            thinking=self._resolve_thinking(state),
        )
        text_parts: list[str] = []
        pending: list[ToolCallRequest] = []
        tool_calls_accum: list[ToolCall] = []
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
                record = await self._sessions.register_artifact(
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
        agents_text = "\n".join(
            f"- {a.agent_id}（{a.display_name}）：{a.description}" for a in index.agents.values()
        )
        system = (
            "你是多智能体平台助手。以下智能体可用：\n"
            f"{agents_text or '（暂无）'}\n"
            "若用户需求匹配某个智能体，请建议用户直接使用。"
        )
        request = ChatRequest(
            messages=[ChatMessage(role="system", content=system), *state.messages],
            thinking=False,
        )
        text_parts: list[str] = []
        async for chunk in self._llm.stream_chat(
            provider=provider, api_key=api_key, request=request
        ):
            if isinstance(chunk, TextChunk):
                self._emit_sync_guard().text_delta(chunk.text)
                text_parts.append(chunk.text)
            elif isinstance(chunk, UsageChunk):
                self._usage.add(chunk)
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
        if state.active_agent is not None:
            package = self._registry.get_agent(state.active_agent)
            if package is not None and package.manifest.model_preference:
                preference = package.manifest.model_preference
        provider_id = preference or self._settings.default_provider_id
        return self._providers.resolve(provider_id)

    def _resolve_thinking(self, state: GraphState) -> bool:
        if not self._settings.thinking_enabled:
            return False
        if state.active_agent is not None:
            package = self._registry.get_agent(state.active_agent)
            if package is not None and package.manifest.thinking_preference == "off":
                return False
        return True

    def _resolve_api_key(self, provider: LLMProvider) -> str:
        return self._api_key_resolver(provider)

    def _trim_context(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        """上下文预算裁剪（§5）：超预算时从最老的助手/工具消息开始裁。"""
        budget = self._settings.context_budget_tokens
        result = list(messages)
        while result and _estimate_tokens(result) > budget:
            candidates = [i for i, m in enumerate(result) if m.role in ("assistant", "tool")]
            if not candidates:
                break
            del result[candidates[0]]
        return result

    async def _route_llm(
        self,
        *,
        candidates_text: str,
        user_input: str,
        tool: ChatToolSpec,
        target_key: str,
        instruction: str,
    ) -> RouteDecision | None:
        provider = self._providers.resolve(self._settings.default_provider_id)
        api_key = self._resolve_api_key(provider)
        request = ChatRequest(
            messages=[
                ChatMessage(role="system", content=instruction),
                ChatMessage(
                    role="user",
                    content=f"候选列表：\n{candidates_text}\n\n用户输入：{user_input}",
                ),
            ],
            tools=[tool],
            thinking=False,
        )
        collected: ToolCallsChunk | None = None
        async for chunk in self._llm.stream_chat(
            provider=provider, api_key=api_key, request=request
        ):
            if isinstance(chunk, ToolCallsChunk):
                collected = chunk
            elif isinstance(chunk, UsageChunk):
                self._usage.add(chunk)
        if collected is None or not collected.tool_calls:
            return None
        call = collected.tool_calls[0]
        data = _parse_args(call.arguments)
        target = data.get(target_key)
        if not isinstance(target, str) or not target:
            return None
        confidence_raw = data.get("confidence", 1.0)
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 1.0
        return RouteDecision(
            target=target, confidence=confidence, reason=str(data.get("reason", ""))
        )
