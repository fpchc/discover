"""单元测试：RunEvent → 对外 SSE 帧映射（run_stream.map_run_event）。

覆盖展示增量（思考/正文/心跳）与终态事件（message_end 携带 usage/assistant）、
失败帧，以及工具/路由等高频事件在对外流中丢弃（返回 None）。
纯函数测试，无网络无 DB。
"""

from app.interfaces.http.run_stream import map_run_event
from app.interfaces.schemas import (
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
    RunCompleted,
    RunFailed,
    TextDelta,
    ThinkingDelta,
    ThinkingEnded,
    ThinkingStarted,
    ToolCallStarted,
)
from app.runtime.models import TerminationReason
from app.shared.errors.base import ErrorCategory

_MESSAGE_ID = "msg-1"
_CONVERSATION_ID = "conv-1"
_CREATED_AT = 1700000000
_USAGE = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
_ASSISTANT = {"type": "expert", "id": "finder"}


def _map(event: object, **kwargs: object) -> object | None:
    return map_run_event(
        event,  # type: ignore[arg-type]  # RunEvent 联合由事件构造保证
        message_id=_MESSAGE_ID,
        conversation_id=_CONVERSATION_ID,
        created_at=_CREATED_AT,
        **kwargs,
    )


def test_thinking_started_maps_to_thinking_start_frame() -> None:
    frame = _map(ThinkingStarted(run_id="r1"))
    assert isinstance(frame, ThinkingStartFrame)
    assert frame.event == "thinking_started"
    assert frame.message_id == _MESSAGE_ID
    assert frame.conversation_id == _CONVERSATION_ID
    assert frame.created_at == _CREATED_AT


def test_thinking_delta_maps_to_thinking_delta_frame() -> None:
    frame = _map(ThinkingDelta(run_id="r1", text="先分析产业链，再圈定候选客户。"))
    assert isinstance(frame, ThinkingDeltaFrame)
    assert frame.event == "thinking_delta"
    assert frame.content == "先分析产业链，再圈定候选客户。"
    assert frame.message_id == _MESSAGE_ID


def test_thinking_ended_maps_to_thinking_end_frame() -> None:
    frame = _map(ThinkingEnded(run_id="r1", duration_ms=1234))
    assert isinstance(frame, ThinkingEndFrame)
    assert frame.event == "thinking_ended"
    assert frame.duration_ms == 1234
    assert frame.conversation_id == _CONVERSATION_ID


def test_text_delta_maps_to_message_frame() -> None:
    frame = _map(TextDelta(run_id="r1", text="报告正文"))
    assert isinstance(frame, MessageEvent)
    assert frame.event == "message"
    assert frame.answer == "报告正文"


def test_run_completed_maps_to_message_end_with_usage_and_assistant() -> None:
    frame = _map(
        RunCompleted(
            run_id="r1",
            status="succeeded",
            termination_reason=TerminationReason.COMPLETED,
        ),
        usage=_USAGE,
        assistant=_ASSISTANT,
    )
    assert isinstance(frame, MessageEndEvent)
    assert frame.event == "message_end"
    assert frame.metadata["usage"] == _USAGE
    assert frame.metadata["assistant"] == _ASSISTANT


def test_heartbeat_maps_to_ping() -> None:
    frame = _map(Heartbeat())
    assert isinstance(frame, PingEvent)
    assert frame.event == "ping"


def test_run_failed_maps_to_error_frame_with_status() -> None:
    frame = _map(
        RunFailed(
            run_id="r1",
            error_category=ErrorCategory.SERVER,
            message="内部错误",
        )
    )
    assert isinstance(frame, ErrorStreamEvent)
    assert frame.event == "error"
    assert frame.status == 500
    assert frame.code == ErrorCategory.SERVER.value
    assert frame.message == "内部错误"


def test_rich_events_dropped_from_outward_stream() -> None:
    # 工具/路由等高频事件在对外流中丢弃，不产生帧
    assert _map(ToolCallStarted(run_id="r1", call_id="c1", tool_name="search")) is None
