"""Step 3 事件协议与 SSE 测试。"""

import asyncio

import pytest
from app.config.settings import Settings
from app.errors.base import ErrorCategory
from app.protocol.emitter import (
    QueueEmitter,
    _BoundedEventQueue,
    _TypewriterChannel,
)
from app.protocol.events import (
    AgentEvent,
    AgentSelectedEvent,
    DoneEvent,
    ErrorEvent,
    HeartbeatEvent,
    TextDeltaEvent,
    ToolCallCompletedEvent,
    event_adapter,
)
from app.protocol.graphemes import split_graphemes
from app.protocol.sanitize import (
    redact_sensitive,
    sanitize_error_message,
    sanitize_tool_args,
    truncate,
)


def test_event_round_trip() -> None:
    event: AgentEvent = AgentSelectedEvent(
        agent_id="discover",
        display_name="EITIA",
        reason="匹配",
        confidence=0.9,
    )
    parsed = event_adapter.validate_json(event.model_dump_json())
    assert parsed == event


def test_event_adapter_picks_variant() -> None:
    raw = (
        '{"type": "tool_call_completed", "seq": 3, "call_id": "c1", "ok": true,'
        ' "result_summary": "ok", "duration_ms": 12, "truncated": false}'
    )
    parsed = event_adapter.validate_json(raw)
    assert isinstance(parsed, ToolCallCompletedEvent)


def test_event_unknown_type_rejected() -> None:
    with pytest.raises(ValueError):
        event_adapter.validate_json('{"type": "not_an_event", "seq": 1}')


async def test_emitter_seq_monotonic() -> None:
    settings = Settings(_env_file=None)
    emitter = QueueEmitter(settings)
    await emitter.emit(
        AgentSelectedEvent(agent_id="a", display_name="A", reason="r", confidence=0.5)
    )
    await emitter.emit(DoneEvent(turns=1, duration_ms=10, usage={}))
    first = await asyncio.wait_for(emitter.get(), timeout=1)
    second = await asyncio.wait_for(emitter.get(), timeout=1)
    assert first.seq == 1
    assert second.seq == 2
    assert isinstance(first, AgentSelectedEvent)
    assert isinstance(second, DoneEvent)


async def test_emitter_text_delta_content_preserved() -> None:
    settings = Settings(_env_file=None)
    emitter = QueueEmitter(settings)
    emitter.text_delta("你好，世界！")
    await emitter.finish()
    text = ""
    while True:
        try:
            event = await asyncio.wait_for(emitter.get(), timeout=0.2)
        except TimeoutError:
            break
        if isinstance(event, TextDeltaEvent):
            text += event.text
    assert text == "你好，世界！"


def test_split_graphemes_cjk() -> None:
    assert split_graphemes("你好") == ["你", "好"]


def test_split_graphemes_combining() -> None:
    assert split_graphemes("é") == ["é"]


def test_split_graphemes_zwj_emoji() -> None:
    family = "\U0001f468‍\U0001f469‍\U0001f467"
    assert split_graphemes(family) == [family]


def test_sanitize_tool_args_redacts_token() -> None:
    summary = '{"api_key": "sk-secret123", "query": "hello"}'
    sanitized = sanitize_tool_args(summary, max_length=300)
    assert "sk-secret123" not in sanitized
    assert "***" in sanitized
    assert "hello" in sanitized


def test_sanitize_env_token() -> None:
    message = "ALIBABA_SEARCH_TOKEN=abc123 调用失败"
    assert "abc123" not in redact_sensitive(message)


def test_sanitize_error_message_truncates() -> None:
    message = "x" * 1000
    sanitized = sanitize_error_message(message, max_length=200)
    assert len(sanitized) < 250
    assert "…" in sanitized


def test_truncate_preserves_head() -> None:
    assert truncate("abcde", max_length=3) == "abc…(截断)"


async def test_bounded_queue_merges_delta_tail() -> None:
    queue = _BoundedEventQueue(maxsize=3)
    await queue.put(TextDeltaEvent(text="你"))
    await queue.put(TextDeltaEvent(text="好"))
    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert isinstance(event, TextDeltaEvent)
    assert event.text == "你好"


async def test_bounded_queue_drops_heartbeat_when_full() -> None:
    queue = _BoundedEventQueue(maxsize=1)
    await queue.put(DoneEvent(turns=1, duration_ms=1, usage={}))
    await asyncio.wait_for(queue.put(HeartbeatEvent()), timeout=1)
    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert isinstance(event, DoneEvent)


async def test_bounded_queue_critical_blocks_when_full() -> None:
    queue = _BoundedEventQueue(maxsize=1)
    await queue.put(DoneEvent(turns=1, duration_ms=1, usage={}))
    put_task = asyncio.create_task(
        queue.put(ErrorEvent(category=ErrorCategory.SERVER, message="x", recoverable=True))
    )
    await asyncio.sleep(0.05)
    assert not put_task.done()
    await queue.get()
    await asyncio.wait_for(put_task, timeout=1)
    assert put_task.done()


def test_typewriter_channel_frames() -> None:
    channel = _TypewriterChannel(
        frame_interval=0.03,
        chars_per_frame=2,
        catchup_threshold=100,
        catchup_ratio=2,
        delta_factory=lambda chunk: TextDeltaEvent(text=chunk),
    )
    channel.append("你好世界")
    first = channel.next_event(force_all=False)
    second = channel.next_event(force_all=False)
    assert first is not None and first.text == "你好"
    assert second is not None and second.text == "世界"
    assert channel.next_event(force_all=False) is None


def test_typewriter_channel_catchup() -> None:
    channel = _TypewriterChannel(
        frame_interval=0.03,
        chars_per_frame=2,
        catchup_threshold=4,
        catchup_ratio=3,
        delta_factory=lambda chunk: TextDeltaEvent(text=chunk),
    )
    channel.append("a" * 20)
    first = channel.next_event(force_all=False)
    assert first is not None and len(first.text) == 6
