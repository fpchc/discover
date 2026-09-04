"""Run 生命周期事件 → SSE 帧映射测试（W6-W7，§17）。

覆盖：终态事件契约（RunCompleted PARTIAL / RunCancelled / RunFailed）、暂停事件
（RunInputRequested 非结束）、高频事件保守丢弃、is_terminal 终态判定。
"""

from __future__ import annotations

from app.interfaces.http.run_stream import (
    is_terminal,
    map_run_event,
)
from app.interfaces.schemas.chat import ErrorStreamEvent, MessageEndEvent
from app.runtime.events.run_events import (
    ContractChecked,
    PhaseStarted,
    RunCancelled,
    RunCompleted,
    RunFailed,
    RunInputRequested,
    RunStarted,
    ToolCallStarted,
)
from app.runtime.models import TerminationReason
from app.shared.errors.base import ErrorCategory

_CTX = {"message_id": "m1", "conversation_id": "c1", "created_at": 1000}


async def test_run_started_maps_to_message_end() -> None:
    frame = map_run_event(RunStarted(type="run_started", run_id="r1"), **_CTX)
    assert isinstance(frame, MessageEndEvent)
    assert frame.metadata.get("phase") == "started"


async def test_run_completed_partial_carries_status_and_reason() -> None:
    event = RunCompleted(
        type="run_completed",
        run_id="r1",
        status="partial",
        termination_reason=TerminationReason.NO_PROGRESS,
        limitations=["数据源不可用"],
        unfinished_phases=["p2"],
    )
    frame = map_run_event(event, **_CTX)
    assert isinstance(frame, MessageEndEvent)
    assert frame.metadata["status"] == "partial"
    assert frame.metadata["reason"] == "no_progress"
    assert frame.metadata["limitations"] == ["数据源不可用"]
    assert frame.metadata["unfinished_phases"] == ["p2"]


async def test_run_cancelled_maps_to_message_end() -> None:
    event = RunCancelled(
        type="run_cancelled",
        run_id="r1",
        termination_reason=TerminationReason.USER_CANCELLED,
    )
    frame = map_run_event(event, **_CTX)
    assert isinstance(frame, MessageEndEvent)
    assert frame.metadata["status"] == "cancelled"


async def test_run_failed_maps_to_error_frame() -> None:
    event = RunFailed(
        type="run_failed",
        run_id="r1",
        termination_reason=TerminationReason.INTERNAL_ERROR,
        error_category=ErrorCategory.SERVER,
        message="内部错误",
    )
    frame = map_run_event(event, **_CTX)
    assert isinstance(frame, ErrorStreamEvent)
    assert frame.code == "server"
    assert frame.status == 500


async def test_run_input_requested_is_pause_not_terminal() -> None:
    event = RunInputRequested(type="run_input_requested", run_id="r1", question="请补充")
    frame = map_run_event(event, **_CTX)
    assert isinstance(frame, MessageEndEvent)
    assert frame.metadata["phase"] == "waiting_input"
    assert is_terminal(event) is False


async def test_high_frequency_events_dropped() -> None:
    """§17：高频运行事件用于实时观测，不对前端逐条下发。"""
    events = [
        ToolCallStarted(type="tool_call_started", run_id="r1"),
        ContractChecked(
            type="contract_checked", run_id="r1", contract_type="structural", verdict="pass"
        ),
    ]
    for event in events:
        assert map_run_event(event, **_CTX) is None


async def test_phase_started_maps_to_message_end() -> None:
    frame = map_run_event(
        PhaseStarted(type="phase_started", run_id="r1", phase_name="查询", attempt=1), **_CTX
    )
    assert isinstance(frame, MessageEndEvent)
    assert frame.metadata["phase"] == "查询"


async def test_is_terminal_distinguishes_terminal_events() -> None:
    completed = RunCompleted(
        type="run_completed",
        run_id="r1",
        status="succeeded",
        termination_reason=TerminationReason.COMPLETED,
    )
    assert is_terminal(completed) is True
    assert is_terminal(RunFailed(type="run_failed", run_id="r1")) is True
    assert is_terminal(RunCancelled(type="run_cancelled", run_id="r1")) is True
    assert is_terminal(RunStarted(type="run_started", run_id="r1")) is False
