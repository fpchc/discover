"""生产适配器（react-runtime-v2-architecture §21 职责边界）。

单一动机：把执行器所需的抽象端口（LLMRunnerPort / ActionGatewayPort）接线到真实
运行组件（LLMClient / ToolBroker）。不包含业务逻辑，只做类型适配。

SSE 帧编码属协议适配，归 `app/interfaces/sse/`——本模块只依赖领域端口词汇与
基础设施客户端，不 import interfaces。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

from app.config.loader import LLMProvider
from app.config.settings import Settings
from app.environment.tools.models import ToolDescriptor
from app.harness.contracts.capability import ToolBrokerPort
from app.harness.execution.pipeline import (
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolPreflightResult,
    ToolRuntime,
)
from app.harness.policy.authorization import AuthorizationContext
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


class ActionGateway:
    """ActionGatewayPort 生产实现：模型工具调用统一入口。

    只做类型适配与运行时默认值合并（workspace / created_by），管线逻辑在
    ToolRuntime 内完成；broker 具体实现仍由装配层注入。
    """

    def __init__(
        self,
        *,
        broker: ToolBrokerPort,
        runtime: ToolRuntime,
        workspace: Path | None = None,
        created_by: str = "agent",
        authorization: AuthorizationContext | None = None,
    ) -> None:
        self._broker = broker
        self._runtime = runtime
        self._workspace = workspace
        self._created_by = created_by
        self._authorization = authorization

    def exposed_tools(self) -> list[ChatToolSpec]:
        return self._broker.exposed_tools()

    def catalog_tool_names(self) -> list[str]:
        return self._broker.catalog_tool_names()

    def get_descriptor(self, name: str) -> ToolDescriptor | None:
        return self._broker.get_descriptor(name)

    async def preflight(self, request: ToolExecutionRequest) -> ToolPreflightResult:
        return await self._runtime.preflight(self._merged(request))

    async def execute_batch(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        merged = self._merged(request)
        return await self._runtime.execute_prepared(merged, merged.calls, [])

    def _merged(self, request: ToolExecutionRequest) -> ToolExecutionRequest:
        """注入运行时默认值（workspace / created_by / authorization）。"""
        merged = request
        if request.workspace is None and self._workspace is not None:
            merged = merged.model_copy(update={"workspace": self._workspace})
        if self._created_by != "agent":
            merged = merged.model_copy(update={"created_by": self._created_by})
        if request.authorization is None and self._authorization is not None:
            merged = merged.model_copy(update={"authorization": self._authorization})
        return merged
