"""生产适配器（react-runtime-v2-architecture §21 职责边界）。

单一动机：把 执行器所需的抽象端口（LLMRunnerPort / ToolRunnerPort /
EventSinkPort）接线到真实运行组件（LLMClient / ToolBroker / SSE 事件流）。
不包含业务逻辑，只做类型适配。

V1 代码将在 W8 切换为默认后下线，本模块是 接入生产链路的核心适配层。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from app.capabilities.llm.client import LLMClient
from app.capabilities.llm.models import ChatRequest, ChatToolSpec
from app.capabilities.llm.providers import ProviderRegistry
from app.capabilities.llm.stream_parser import SemanticChunk
from app.capabilities.tools.broker import ToolBroker, ToolCallRequest, ToolResult
from app.capabilities.tools.descriptor import ToolDescriptor
from app.config.loader import LLMProvider
from app.config.settings import Settings
from app.runtime.events.run_events import RunEvent


class LLMRunner:
    """LLMRunnerPort 生产实现：包装 LLMClient + ProviderRegistry + resolve_api_key。"""

    def __init__(
        self,
        client: LLMClient,
        providers: ProviderRegistry,
        resolve_api_key: Callable[[LLMProvider], str],
        settings: Settings,
    ) -> None:
        self._client = client
        self._providers = providers
        self._resolve_api_key = resolve_api_key
        self._settings = settings

    def stream(self, *, request: ChatRequest) -> AsyncIterator[SemanticChunk]:
        provider = self._providers.resolve(self._settings.default_provider_id)
        api_key = self._resolve_api_key(provider)
        return self._client.stream_chat(provider=provider, api_key=api_key, request=request)


class ToolRunner:
    """ToolRunnerPort 生产实现：包装 ToolBroker（已激活的会话级实例）。"""

    def __init__(self, broker: ToolBroker) -> None:
        self._broker = broker

    def exposed_tools(self) -> list[ChatToolSpec]:
        return self._broker.exposed_tools()

    def catalog_tool_names(self) -> list[str]:
        return self._broker.catalog_tool_names()

    def get_descriptor(self, name: str) -> ToolDescriptor | None:
        return self._broker.get_descriptor(name)

    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]:
        return await self._broker.execute(calls)


class SSEEventSink:
    """EventSinkPort 生产实现：把 RunEvent 经 run_stream 映射为 SSE 帧后推送。

    push_frame 回调由 chat.py 的路由层提供（写 SSE 帧流或收集帧队列）。
    """

    def __init__(
        self,
        push_frame: Callable[[object], object],
        message_id: str,
        conversation_id: str,
        created_at: int,
    ) -> None:
        self._push = push_frame
        self._message_id = message_id
        self._conversation_id = conversation_id
        self._created_at = created_at

    async def emit(self, event: RunEvent) -> None:
        from app.interfaces.http.run_stream import map_run_event

        frame = map_run_event(
            event,
            message_id=self._message_id,
            conversation_id=self._conversation_id,
            created_at=self._created_at,
        )
        if frame is not None:
            result = self._push(frame)
            if hasattr(result, "__await__"):
                await result
