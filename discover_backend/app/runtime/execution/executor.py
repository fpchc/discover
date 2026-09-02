"""工具执行协调器（runtime/execution）：Action → Tool/MCP → Observation → 状态回写。

把 Runtime 的 tool_node 中「分发 + 事件 + 门禁 + 产物登记」抽为 ToolExecutor，
Engine 只负责状态转移；ToolBroker 仍是唯一执行出口。为未来 SOP → State Machine →
ReAct（Action/Observation 循环）预留词汇，新增执行阶段不改 Engine。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.capabilities.llm.models import ChatMessage
from app.capabilities.tools.broker import ToolBroker, ToolCallRequest
from app.domain.file.service import FileService, file_preview_path
from app.interfaces.schemas.files import ArtifactRecord
from app.runtime.events.emitter import QueueEmitter
from app.runtime.events.events import (
    ArtifactReadyEvent,
    GateCheckedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from app.runtime.state import GateStatus
from app.shared.utils.sanitize import sanitize_tool_args, truncate

_GATE_MARKER = ".script.gate_"
_EVENT_ARGS_SUMMARY_CHARS = 200
_EVENT_RESULT_SUMMARY_CHARS = 300


def _gate_id_from_tool(tool_name: str) -> str | None:
    if _GATE_MARKER not in tool_name:
        return None
    return tool_name.split(_GATE_MARKER, 1)[1]


class ToolExecutionOutcome(BaseModel):
    """单批工具执行的回合回写：模型可见消息 / 门禁状态 / 产物登记。"""

    messages: list[ChatMessage] = Field(default_factory=list)
    gate_status: dict[str, GateStatus] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)


class ToolExecutor:
    """工具执行器：Action 列表 → ToolBroker 分发 → Observation 聚合 + 状态回写。"""

    def __init__(self, broker: ToolBroker, files: FileService) -> None:
        self._broker = broker
        self._files = files

    async def execute(
        self,
        calls: list[ToolCallRequest],
        *,
        emitter: QueueEmitter,
        account_id: str,
        workspace: Path,
        turn: int,
    ) -> ToolExecutionOutcome:
        for call in calls:
            summary = sanitize_tool_args(
                json.dumps(call.arguments, ensure_ascii=False),
                max_length=_EVENT_ARGS_SUMMARY_CHARS,
            )
            await emitter.emit(
                ToolCallStartedEvent(
                    call_id=call.call_id, tool_name=call.tool_name, args_summary=summary
                )
            )
        results = await self._broker.execute(calls)
        messages: list[ChatMessage] = []
        gate_updates: dict[str, GateStatus] = {}
        artifacts: list[ArtifactRecord] = []
        for result in results:
            await emitter.emit(
                ToolCallCompletedEvent(
                    call_id=result.call_id,
                    ok=result.ok,
                    result_summary=truncate(
                        result.content or result.message, max_length=_EVENT_RESULT_SUMMARY_CHARS
                    ),
                    duration_ms=result.duration_ms,
                    truncated=result.truncated,
                )
            )
            messages.append(
                ChatMessage(
                    role="tool",
                    content=result.content or result.message,
                    tool_call_id=result.call_id,
                )
            )
            gate_id = _gate_id_from_tool(result.tool_name)
            if gate_id is not None:
                failures = [] if result.ok else [result.message]
                gate_updates[gate_id] = GateStatus(passed=result.ok, failures=failures, turn=turn)
                await emitter.emit(
                    GateCheckedEvent(gate_id=gate_id, passed=result.ok, failures=failures)
                )
            for rel in result.produced_files:
                record = await self._files.register(
                    created_by=account_id,
                    source_path=workspace / rel,
                    filename=Path(rel).name,
                )
                await emitter.emit(
                    ArtifactReadyEvent(
                        artifact_id=record.artifact_id,
                        filename=record.filename,
                        media_type=record.media_type,
                        size_bytes=record.size_bytes,
                        download_url=file_preview_path(record),
                    )
                )
                artifacts.append(record)
        return ToolExecutionOutcome(
            messages=messages, gate_status=gate_updates, artifacts=artifacts
        )
