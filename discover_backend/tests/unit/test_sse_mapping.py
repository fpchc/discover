"""单元测试：内部 AgentEvent → 对外 SSE 帧映射（routes_chat._map_stream_event）。

覆盖思考事件独立映射为 thinking_* 帧、正文/心跳/错误/完成映射，以及
路由/工具等富事件在对外流中丢弃（返回 None）。纯函数测试，无网络无 DB。
"""

from platform_engine.api.models import (
    ErrorStreamEvent,
    MessageEndEvent,
    MessageEvent,
    PingEvent,
    ThinkingDeltaFrame,
    ThinkingEndFrame,
    ThinkingStartFrame,
)
from platform_engine.api.routes_chat import _map_stream_event
from platform_engine.errors.base import ErrorCategory
from platform_engine.protocol.events import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    HeartbeatEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ThinkingEndedEvent,
    ThinkingStartedEvent,
    ToolCallStartedEvent,
)

_MESSAGE_ID = "msg-1"
_CONVERSATION_ID = "conv-1"
_CREATED_AT = 1700000000


def _map(event: AgentEvent) -> object | None:
    return _map_stream_event(
        event,
        message_id=_MESSAGE_ID,
        conversation_id=_CONVERSATION_ID,
        created_at=_CREATED_AT,
    )


def test_thinking_started_maps_to_thinking_start_frame() -> None:
    frame = _map(ThinkingStartedEvent())
    assert isinstance(frame, ThinkingStartFrame)
    assert frame.event == "thinking_started"
    assert frame.message_id == _MESSAGE_ID
    assert frame.conversation_id == _CONVERSATION_ID
    assert frame.created_at == _CREATED_AT


def test_thinking_delta_maps_to_thinking_delta_frame() -> None:
    frame = _map(ThinkingDeltaEvent(text="先分析产业链，再圈定候选客户。"))
    assert isinstance(frame, ThinkingDeltaFrame)
    assert frame.event == "thinking_delta"
    assert frame.content == "先分析产业链，再圈定候选客户。"
    assert frame.message_id == _MESSAGE_ID


def test_thinking_ended_maps_to_thinking_end_frame() -> None:
    frame = _map(ThinkingEndedEvent(duration_ms=1234))
    assert isinstance(frame, ThinkingEndFrame)
    assert frame.event == "thinking_ended"
    assert frame.duration_ms == 1234
    assert frame.conversation_id == _CONVERSATION_ID


def test_text_delta_maps_to_message_frame() -> None:
    frame = _map(TextDeltaEvent(text="报告正文"))
    assert isinstance(frame, MessageEvent)
    assert frame.event == "message"
    assert frame.answer == "报告正文"


def test_done_maps_to_message_end_with_compat_usage() -> None:
    frame = _map(
        DoneEvent(turns=2, duration_ms=500, usage={"input": 10, "output": 20, "total": 30})
    )
    assert isinstance(frame, MessageEndEvent)
    assert frame.event == "message_end"
    assert frame.metadata["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
    }


def test_heartbeat_maps_to_ping() -> None:
    frame = _map(HeartbeatEvent())
    assert isinstance(frame, PingEvent)
    assert frame.event == "ping"


def test_error_maps_to_error_frame_with_status() -> None:
    frame = _map(
        ErrorEvent(
            category=ErrorCategory.SERVER,
            message="内部错误",
            recoverable=False,
            suggestion="请重试",
        )
    )
    assert isinstance(frame, ErrorStreamEvent)
    assert frame.event == "error"
    assert frame.status == 500
    assert frame.code == ErrorCategory.SERVER.value
    assert frame.message == "内部错误"


def test_rich_events_dropped_from_outward_stream() -> None:
    # 路由/工具等富事件在对外流中丢弃，不产生帧
    assert _map(ToolCallStartedEvent(call_id="c1", tool_name="search", args_summary="{}")) is None
