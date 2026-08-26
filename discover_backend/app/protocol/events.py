"""SSE 事件模型：前端与平台的唯一契约。

事件类型为判别字段（pydantic 判别联合）；每个事件带单会话内单调递增序号，
前端用于排序与去重（SSE 重连可能重复投递）。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.errors.base import ErrorCategory


class AgentEvent(BaseModel):
    """事件基类。seq 由发射器统一分配。"""

    type: str
    seq: int = 0


class SessionCreatedEvent(AgentEvent):
    """会话建立。"""

    type: Literal["session_created"] = "session_created"
    session_id: str


class AgentSelectedEvent(AgentEvent):
    """智能体选定。"""

    type: Literal["agent_selected"] = "agent_selected"
    agent_id: str
    display_name: str
    reason: str
    confidence: float


class SkillSelectedEvent(AgentEvent):
    """技能选定。"""

    type: Literal["skill_selected"] = "skill_selected"
    skill_id: str
    reason: str


class ToolsReadyEvent(AgentEvent):
    """工具就绪。"""

    type: Literal["tools_ready"] = "tools_ready"
    core_count: int
    catalog_size: int
    started_services: list[str]


class ThinkingStartedEvent(AgentEvent):
    """思考开始。"""

    type: Literal["thinking_started"] = "thinking_started"


class ThinkingDeltaEvent(AgentEvent):
    """思考增量。"""

    type: Literal["thinking_delta"] = "thinking_delta"
    text: str


class ThinkingEndedEvent(AgentEvent):
    """思考结束。"""

    type: Literal["thinking_ended"] = "thinking_ended"
    duration_ms: int


class TextDeltaEvent(AgentEvent):
    """正文增量。"""

    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolCallStartedEvent(AgentEvent):
    """工具调用发起。"""

    type: Literal["tool_call_started"] = "tool_call_started"
    call_id: str
    tool_name: str
    args_summary: str


class ToolCallCompletedEvent(AgentEvent):
    """工具调用完成。"""

    type: Literal["tool_call_completed"] = "tool_call_completed"
    call_id: str
    ok: bool
    result_summary: str
    duration_ms: int
    truncated: bool


class GateCheckedEvent(AgentEvent):
    """门禁校验。"""

    type: Literal["gate_checked"] = "gate_checked"
    gate_id: str
    passed: bool
    failures: list[str]


class SourceDegradedEvent(AgentEvent):
    """数据源降级。"""

    type: Literal["source_degraded"] = "source_degraded"
    source: str
    reason: str
    degrade_note: str


class ArtifactReadyEvent(AgentEvent):
    """产物就绪。"""

    type: Literal["artifact_ready"] = "artifact_ready"
    artifact_id: str
    filename: str
    media_type: str
    size_bytes: int
    download_url: str


class ErrorEvent(AgentEvent):
    """错误。"""

    type: Literal["error"] = "error"
    category: ErrorCategory
    message: str
    recoverable: bool
    suggestion: str | None = None


class DoneEvent(AgentEvent):
    """完成。

    usage 键：input/output/total/cached_read/cached_write（回合聚合）；
    provider/model 为本回合生效的模型快照（供历史落库与计费消费）。
    """

    type: Literal["done"] = "done"
    turns: int
    duration_ms: int
    usage: dict[str, int]
    provider: str | None = None
    model: str | None = None


class HeartbeatEvent(AgentEvent):
    """心跳。"""

    type: Literal["heartbeat"] = "heartbeat"


AgentEventUnion = Annotated[
    AgentSelectedEvent
    | ArtifactReadyEvent
    | DoneEvent
    | ErrorEvent
    | GateCheckedEvent
    | HeartbeatEvent
    | SessionCreatedEvent
    | SkillSelectedEvent
    | SourceDegradedEvent
    | TextDeltaEvent
    | ThinkingDeltaEvent
    | ThinkingEndedEvent
    | ThinkingStartedEvent
    | ToolCallCompletedEvent
    | ToolCallStartedEvent
    | ToolsReadyEvent,
    Field(discriminator="type"),
]

event_adapter: TypeAdapter[AgentEventUnion] = TypeAdapter(AgentEventUnion)
