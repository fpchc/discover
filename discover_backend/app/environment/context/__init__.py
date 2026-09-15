"""Agent 上下文事实与来源端口（agent-context-plane-spec）。

对外 Facade：结构化上下文事实模型 + 来源端口。回答「系统有哪些事实」。

边界（P1#9）：「本轮选择 / 裁剪 / 压缩 / 注入 / 投影为模型消息」已拆到
`app.harness.context`（ContextAssembler / ContextProjector）；本包只保留事实模型与
来源端口。来源端口的生产适配器（包装 ConversationService / FileService）位于
`app/application/context/adapters.py`——适配器由业务侧提供，环境只认端口。
"""

from app.environment.context.models import (
    AgentContext,
    ArtifactContext,
    ArtifactRef,
    AttachmentContext,
    AttachmentSourceType,
    ContextAssemblyOptions,
    ContextConstraints,
    ContextDelta,
    ContextIdentity,
    ContextMessage,
    ContextSummary,
    ConversationContext,
    CurrentInput,
    EvidenceContext,
    FileRef,
    MemoryContext,
    MemoryUpdate,
    ObservationRef,
    WorkflowContext,
)
from app.environment.context.ports import AttachmentContextPort, ConversationContextPort

__all__ = [
    "AgentContext",
    "ArtifactContext",
    "ArtifactRef",
    "AttachmentContext",
    "AttachmentContextPort",
    "AttachmentSourceType",
    "ContextAssemblyOptions",
    "ContextConstraints",
    "ContextDelta",
    "ContextIdentity",
    "ContextMessage",
    "ContextSummary",
    "ConversationContext",
    "ConversationContextPort",
    "CurrentInput",
    "EvidenceContext",
    "FileRef",
    "MemoryContext",
    "MemoryUpdate",
    "ObservationRef",
    "WorkflowContext",
]
