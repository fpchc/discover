"""Run 生命周期事件 → 对外 SSE 帧映射（react-runtime-v2-architecture §17）。

单一动机：HTTP/SSE 只负责映射，不感知 LangGraph 内部节点（§21）。生命周期
事件（RunEvent 集）经本模块归一为对外帧；终态事件契约（§17.1）——RunCompleted
（SUCCEEDED|PARTIAL）表达正常完成类终态、RunFailed 表达无可交付结果、
RunCancelled 单独表达取消。断连与取消分离（§17.3）：本层不因客户端断连产生取消。

纯函数：便于单测；展示增量（正文/思考/心跳）与生命周期事件统一经 RunEvent
映射，不再区分旧 AgentEvent 链路。
"""

from __future__ import annotations

from app.interfaces.schemas.chat import (
    ErrorStreamEvent,
    MessageEndEvent,
    MessageEvent,
    PingEvent,
    ThinkingDeltaFrame,
    ThinkingEndFrame,
    ThinkingStartFrame,
)
from app.runtime.events.run_events import (
    Heartbeat,
    PhaseStarted,
    RunCancelled,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunInputRequested,
    RunStarted,
    TextDelta,
    ThinkingDelta,
    ThinkingEnded,
    ThinkingStarted,
)

# 对外 SSE 帧判别联合（与 schemas.chat._StreamFrame 同构；独立定义避免反向依赖）
_StreamFrame = (
    ErrorStreamEvent
    | MessageEndEvent
    | MessageEvent
    | PingEvent
    | ThinkingDeltaFrame
    | ThinkingEndFrame
    | ThinkingStartFrame
)


def map_run_event(
    event: RunEvent,
    *,
    message_id: str,
    conversation_id: str,
    created_at: int,
    usage: dict[str, int] | None = None,
    assistant: dict[str, str | None] | None = None,
) -> _StreamFrame | None:
    """RunEvent → 对外 SSE 帧（纯函数）。

    - 终态事件（RunCompleted / RunFailed / RunCancelled）→ message_end 帧，
      携带 status / reason / limitations（§17.1）；
    - RunInputRequested → message_end（暂停事件，非结束，§17.2）；
    - 高频运行事件（工具调用 / 进度 / Contract / 阶段切换）→ 返回 None（观测用，
      不对前端逐条下发，避免撑爆 SSE）；
    - 未知事件 → None（保守丢弃，不破坏既有流）。
    """
    if isinstance(event, RunStarted):
        return _message_end(message_id, conversation_id, created_at, {"phase": "started"})
    if isinstance(event, PhaseStarted):
        return _message_end(
            message_id,
            conversation_id,
            created_at,
            {"phase": event.phase_name or "phase", "attempt": event.attempt},
        )
    if isinstance(event, RunInputRequested):
        return _message_end(
            message_id,
            conversation_id,
            created_at,
            {
                "phase": "waiting_input",
                "question": event.question,
                "missing_fields": event.missing_fields,
            },
        )
    if isinstance(event, RunCompleted):
        return _message_end(
            message_id,
            conversation_id,
            created_at,
            {
                "status": event.status,
                "reason": event.termination_reason.value,
                "limitations": event.limitations,
                "unfinished_phases": event.unfinished_phases,
            },
            usage=usage,
            assistant=assistant,
        )
    if isinstance(event, RunCancelled):
        return _message_end(
            message_id,
            conversation_id,
            created_at,
            {"status": "cancelled", "reason": event.termination_reason.value},
            usage=usage,
            assistant=assistant,
        )
    if isinstance(event, RunFailed):
        return ErrorStreamEvent(
            status=_http_status(event),
            code=_error_code(event),
            message=event.message or "执行失败",
        )
    if isinstance(event, ThinkingStarted):
        return ThinkingStartFrame(
            message_id=message_id,
            conversation_id=conversation_id,
            created_at=created_at,
        )
    if isinstance(event, ThinkingDelta):
        return ThinkingDeltaFrame(
            message_id=message_id,
            conversation_id=conversation_id,
            content=event.text,
            created_at=created_at,
        )
    if isinstance(event, ThinkingEnded):
        return ThinkingEndFrame(
            message_id=message_id,
            conversation_id=conversation_id,
            duration_ms=event.duration_ms,
            created_at=created_at,
        )
    if isinstance(event, TextDelta):
        return MessageEvent(
            message_id=message_id,
            conversation_id=conversation_id,
            answer=event.text,
            created_at=created_at,
        )
    if isinstance(event, Heartbeat):
        return PingEvent()
    # 高频运行事件：不逐条下发（§17 高频事件用于实时观测，不等同于 Checkpoint）
    return None


def _message_end(
    message_id: str,
    conversation_id: str,
    created_at: int,
    metadata: dict[str, object],
    *,
    usage: dict[str, int] | None = None,
    assistant: dict[str, str | None] | None = None,
) -> MessageEndEvent:
    if usage is not None:
        metadata["usage"] = usage
    if assistant is not None:
        metadata["assistant"] = assistant
    return MessageEndEvent(
        message_id=message_id,
        conversation_id=conversation_id,
        metadata=metadata,
        created_at=created_at,
    )


def _http_status(event: RunFailed) -> int:
    if event.error_category is not None:
        from app.shared.errors.base import http_status_for

        return http_status_for(event.error_category)
    return 500


def _error_code(event: RunFailed) -> str:
    if event.error_category is not None:
        return event.error_category.value
    return "internal_error"


# 供外部判断是否终态（SSE 明确终止事件，§17.2）
_TERMINAL_TYPES = frozenset({"run_completed", "run_failed", "run_cancelled"})


def is_terminal(event: RunEvent) -> bool:
    """终态事件判断：HTTP 层据此结束 SSE 流（不靠「队列为空」猜测）。"""
    return event.type in _TERMINAL_TYPES
