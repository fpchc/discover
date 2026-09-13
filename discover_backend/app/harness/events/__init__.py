"""Harness 事件：RunEvent 生命周期契约 + 会话级事件发射器。"""

from app.harness.events.emitter import QueueEmitter
from app.harness.events.run_events import (
    TERMINAL_EVENT_TYPES,
    RunEvent,
    RunEventUnion,
    is_terminal,
    run_event_adapter,
)

__all__ = [
    "TERMINAL_EVENT_TYPES",
    "QueueEmitter",
    "RunEvent",
    "RunEventUnion",
    "is_terminal",
    "run_event_adapter",
]
