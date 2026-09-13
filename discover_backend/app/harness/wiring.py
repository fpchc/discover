"""生产适配器（react-runtime-v2-architecture §21 职责边界）。

单一动机：把执行器所需的抽象端口（LLMRunnerPort / ToolRunnerPort）接线到真实
运行组件（LLMClient / ToolBroker）。不包含业务逻辑，只做类型适配。

SSE 帧编码属协议适配，归 `app/interfaces/sse/`——本模块只依赖领域端口词汇与
基础设施客户端，不 import interfaces。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from app.config.loader import LLMProvider
from app.config.settings import Settings
from app.environment.tools.broker import ToolBroker
from app.environment.tools.models import ToolCallRequest, ToolDescriptor, ToolResult
from app.llm.chunks import SemanticChunk
from app.llm.client import LLMClient
from app.llm.models import ChatRequest, ChatToolSpec
from app.llm.providers import ProviderRegistry


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
