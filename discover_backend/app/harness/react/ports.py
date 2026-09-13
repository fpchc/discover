"""Bounded ReAct 执行器的端口（DIP）：LLM 流 / 工具运行 / 事件发射。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from app.environment.tools.models import ToolCallRequest, ToolDescriptor, ToolResult
from app.harness.events.run_events import RunEvent
from app.llm.chunks import SemanticChunk
from app.llm.models import ChatRequest, ChatToolSpec


class LLMRunnerPort(Protocol):
    """LLM 流式调用抽象：隐藏 provider / api_key 解析（组装层适配）。

    声明为异步生成器签名（def + AsyncIterator），供 ``async for`` 消费。
    """

    def stream(self, *, request: ChatRequest) -> AsyncIterator[SemanticChunk]: ...


class ToolRunnerPort(Protocol):
    """工具执行抽象：目录查询 + 分发（ToolBroker 实现，唯一出口）。"""

    def exposed_tools(self) -> list[ChatToolSpec]: ...
    def get_descriptor(self, name: str) -> ToolDescriptor | None: ...
    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]: ...


class EventSinkPort(Protocol):
    """Run 事件发射抽象：SSE / 审计 / 观测统一出口。"""

    async def emit(self, event: RunEvent) -> None: ...
