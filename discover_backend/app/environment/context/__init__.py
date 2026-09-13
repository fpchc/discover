"""Agent 上下文平面（agent-context-plane-spec）。

对外 Facade：结构化上下文模型 + 来源端口 + 装配器 + 投影器。
规范见 `specs/agent-context-plane-spec.md`；当前代码路径见 `docs/MODULE_MAP.md`。

来源端口的生产适配器（包装 ConversationService / FileService）位于
`app/application/context/adapters.py`——适配器由业务侧提供，环境只认端口。
"""

from app.environment.context.assembler import ContextAssembler
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
from app.environment.context.projector import ContextProjector

__all__ = [
    "AgentContext",
    "ArtifactContext",
    "ArtifactRef",
    "AttachmentContext",
    "AttachmentContextPort",
    "AttachmentSourceType",
    "ContextAssembler",
    "ContextAssemblyOptions",
    "ContextConstraints",
    "ContextDelta",
    "ContextIdentity",
    "ContextMessage",
    "ContextProjector",
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
