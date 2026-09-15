"""Bounded ReAct 执行器的端口（DIP）：LLM 流 / 工具运行 / 事件发射。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from app.environment.tools.models import ToolDescriptor
from app.harness.events.run_events import RunEvent
from app.harness.execution.pipeline import (
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolPreflightResult,
)
from app.llm.chunks import SemanticChunk
from app.llm.models import ChatRequest, ChatToolSpec


class LLMRunnerPort(Protocol):
    """LLM 流式调用抽象：隐藏 provider / api_key 解析（组装层适配）。

    声明为异步生成器签名（def + AsyncIterator），供 ``async for`` 消费。
    """

    def stream(self, *, request: ChatRequest) -> AsyncIterator[SemanticChunk]: ...


class ActionGatewayPort(Protocol):
    """行动网关：模型提出的工具执行只允许经此入口。

    统一承担 preflight（存在性/白名单/schema/重复无进展）与执行
    （副作用预记录 → broker → normalize → 产物登记）。执行器不得直接持有
    ToolBroker 执行模型工具调用。
    """

    def exposed_tools(self) -> list[ChatToolSpec]: ...
    def get_descriptor(self, name: str) -> ToolDescriptor | None: ...
    async def preflight(self, request: ToolExecutionRequest) -> ToolPreflightResult: ...
    async def execute_batch(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...


class EventSinkPort(Protocol):
    """Run 事件发射抽象：SSE / 审计 / 观测统一出口。"""

    async def emit(self, event: RunEvent) -> None: ...
