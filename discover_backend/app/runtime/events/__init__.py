"""事件契约（runtime 输出）：AgentEvent 事件模型 + QueueEmitter 会话级发射器。

事件由 runtime 节点产出，经 emitter（seq / 打字机 / 心跳 / 背压）下发，
Interface 层消费并映射为 SSE 帧。
"""

from app.runtime.events.emitter import QueueEmitter
from app.runtime.events.events import (
    AgentEvent,
    AgentEventUnion,
    AgentSelectedEvent,
    ArtifactReadyEvent,
    DoneEvent,
    ErrorEvent,
    GateCheckedEvent,
    HeartbeatEvent,
    SessionCreatedEvent,
    SkillSelectedEvent,
    SourceDegradedEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ThinkingEndedEvent,
    ThinkingStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
    ToolsReadyEvent,
    event_adapter,
)

__all__ = [
    "AgentEvent",
    "AgentEventUnion",
    "AgentSelectedEvent",
    "ArtifactReadyEvent",
    "DoneEvent",
    "ErrorEvent",
    "GateCheckedEvent",
    "HeartbeatEvent",
    "QueueEmitter",
    "SessionCreatedEvent",
    "SkillSelectedEvent",
    "SourceDegradedEvent",
    "TextDeltaEvent",
    "ThinkingDeltaEvent",
    "ThinkingEndedEvent",
    "ThinkingStartedEvent",
    "ToolCallCompletedEvent",
    "ToolCallStartedEvent",
    "ToolsReadyEvent",
    "event_adapter",
]
