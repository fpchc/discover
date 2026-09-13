"""Agent 上下文平面模型（agent-context-plane-spec §4）。

单一动机：定义「Agent 在某个执行时点能看到什么」的结构化快照与来源引用。
本模块是纯模型层：不访问数据库 / 存储 / 网络，不调用 LLM，不依赖 FastAPI 或
具体基础设施（规范 §5.1 职责边界）。

硬约束（规范 §3、§4.1、§10）：

- 全部使用 Pydantic v2，可序列化 / 反序列化；
- 只保存引用、摘要、受控快照、版本与来源元数据，不复制文件正文或工具原始输出；
- 禁止用无边界的 `dict[str, object]` 充当统一上下文模型；`phase_input` 等已声明
  的结构化 payload 例外（规范 §4.1）。

与目标态的差距：`ContextRole` 目前只含运行时已支持投影的四种角色，
observation / artifact 角色待 LLM 消息模型扩展后加入（规范 §4.4）。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# LLM 消息当前可承载的角色集合（与 ChatMessage 契约一致）。
# observation / artifact 属规范 §4.4 目标态，需先扩展 LLM 消息模型。
ContextRole = Literal["system", "user", "assistant", "tool"]


class ContextIdentity(BaseModel):
    """上下文身份（规范 §4.2）：Run / 会话 / 消息 / 账号 / 阶段 + 版本。"""

    run_id: str = ""
    conversation_id: str = ""
    message_id: str = ""
    account_id: str = ""
    phase_instance_id: str = ""
    context_version: int = 1


class ContextMessage(BaseModel):
    """会话消息的结构化形态（规范 §4.4）。

    `message_id` 留空表示来源尚未提供角色级消息 ID（当前 messages 表为
    query/answer 单行拍平模型，见规范 §2.4）；此时用 `source_ref` 保留可追踪性。
    """

    role: ContextRole
    content: str = ""
    message_id: str = ""
    conversation_id: str = ""
    parent_id: str | None = None
    created_at: datetime | None = None
    source_ref: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)


class CurrentInput(BaseModel):
    """当前输入（规范 §4.3）：本轮用户消息必须是独立结构化对象。

    禁止只以 `phase_input["user_goal"]` 或 system prompt 拼接传递当前输入。
    """

    text: str
    message_id: str = ""
    file_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class ContextSummary(BaseModel):
    """上下文摘要（规范 §6.3）：摘要必须可追踪覆盖范围与来源版本。"""

    summary: str = ""
    source: str = ""
    covered_message_ids: list[str] = Field(default_factory=list)
    covered_message_range: str = ""
    created_at: datetime | None = None
    context_version: int = 1


class ConversationContext(BaseModel):
    """会话上下文（规范 §4.4）：摘要 + 选中消息 + 引用。"""

    summary: ContextSummary | None = None
    recent_messages: list[ContextMessage] = Field(default_factory=list)
    pinned_messages: list[ContextMessage] = Field(default_factory=list)
    message_refs: list[str] = Field(default_factory=list)
    covered_message_range: str = ""


class AttachmentSourceType(StrEnum):
    """附件来源类型（规范 §4.5）：用户上传 / Agent 产物 / 外部引用。"""

    USER_UPLOAD = "user_upload"
    AGENT_ARTIFACT = "agent_artifact"
    EXTERNAL_REFERENCE = "external_reference"


class FileRef(BaseModel):
    """文件引用（规范 §4.5）：只带元数据与存储引用，不带正文。

    文件内容进入上下文必须经 `Context → FileRef → FileService / Storage / Parser`
    受控读取，不得默认复制进 Graph State。
    """

    file_id: str
    name: str = ""
    media_type: str = ""
    size_bytes: int = 0
    message_id: str = ""
    conversation_id: str = ""
    run_id: str = ""
    created_by: str = ""
    created_by_role: str = ""
    storage_ref: str = ""
    extraction_status: str = ""
    access_scope: str = ""
    source_type: AttachmentSourceType = AttachmentSourceType.USER_UPLOAD


class AttachmentContext(BaseModel):
    """附件上下文（规范 §4.5）：默认只保存引用。"""

    files: list[FileRef] = Field(default_factory=list)


class ObservationRef(BaseModel):
    """工具观察引用（规范 §4.6）：完整原始结果留在对应 Store / Blob。

    `confidence` 为可选外部资料可信度（0~1）；`truncated` 标记结果已被裁剪。
    """

    observation_id: str = ""
    source_ref: str = ""
    content_summary: str = ""
    content_blob_ref: str | None = None
    confidence: float | None = None
    created_at: datetime | None = None
    truncated: bool = False
    artifact_ids: list[str] = Field(default_factory=list)


class EvidenceContext(BaseModel):
    """证据上下文（规范 §4.6）。"""

    observations: list[ObservationRef] = Field(default_factory=list)


class ArtifactRef(BaseModel):
    """产物引用（规范 §4.5 / §8）：Agent 生成物与用户上传可区分。"""

    artifact_id: str
    name: str = ""
    media_type: str = ""
    source_ref: str = ""
    created_by_role: str = ""
    created_at: datetime | None = None


class ArtifactContext(BaseModel):
    """产物上下文。"""

    artifacts: list[ArtifactRef] = Field(default_factory=list)


class MemoryContext(BaseModel):
    """长期记忆上下文（规范 §3.5）：独立 Memory Store 的受控投影。

    本阶段只定义载体，长期记忆 Store 接入属后续阶段（规范 §14 明确不做）。
    """

    notes: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class WorkflowContext(BaseModel):
    """多阶段上下文（规范 §4.7）。`phase_input` 为已声明的结构化阶段输入。"""

    current_phase_id: str = ""
    phase_goal: str = ""
    phase_input: dict[str, object] = Field(default_factory=dict)
    upstream_output_refs: list[str] = Field(default_factory=list)
    completed_phase_ids: list[str] = Field(default_factory=list)
    pending_requirements: list[str] = Field(default_factory=list)


class ContextConstraints(BaseModel):
    """Agent 可见业务约束（规范 §4.8）。

    预算用量 / 取消 / 租约 / 终止属 Runtime 控制平面，不得放入本模型，也不得被
    用户消息、文件正文或工具结果直接修改（规范 §4.8、§10.13）。
    """

    allowed_tools: list[str] = Field(default_factory=list)
    output_contract_refs: list[str] = Field(default_factory=list)
    access_scope: str = ""
    locale: str = ""
    timezone: str = ""
    context_token_budget: int | None = None


class MemoryUpdate(BaseModel):
    """长期记忆更新意图（规范 §5.2 ContextDelta.memory_updates 元素）。"""

    text: str
    source_ref: str = ""


class AgentContext(BaseModel):
    """Agent 可见上下文的结构化快照（规范 §3.3 / §4.1）。

    这是「某个执行时点 Agent 能看到什么」的快照，不是所有业务事实的永久主存储；
    事实来源仍是 Conversation / File / Run / Observation / Artifact 各 Store。
    """

    current_input: CurrentInput
    identity: ContextIdentity = Field(default_factory=ContextIdentity)
    conversation: ConversationContext = Field(default_factory=ConversationContext)
    attachments: AttachmentContext = Field(default_factory=AttachmentContext)
    memory: MemoryContext = Field(default_factory=MemoryContext)
    workflow: WorkflowContext = Field(default_factory=WorkflowContext)
    evidence: EvidenceContext = Field(default_factory=EvidenceContext)
    artifacts: ArtifactContext = Field(default_factory=ArtifactContext)
    constraints: ContextConstraints = Field(default_factory=ContextConstraints)
    version: int = 1


class ContextDelta(BaseModel):
    """上下文增量（规范 §5.2）：工具结果 / 产物 / 观察 / 记忆更新的结构化入口。

    本阶段只定义模型；`ContextReducer` 的应用链路属后续阶段（规范 §11 阶段六），
    当前不得让工具直接修改 Conversation / Run 或共享状态。
    `evidence` 暂以 `ObservationRef` 承载（规范 §4.6），避免定义无字段差异的重复类型。
    """

    messages: list[ContextMessage] = Field(default_factory=list)
    observations: list[ObservationRef] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    evidence: list[ObservationRef] = Field(default_factory=list)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ContextAssemblyOptions(BaseModel):
    """装配期确定性裁剪预算（规范 §6.1：裁剪不得使用随机策略）。

    `0` 表示该维度不限制。裁剪按「从最近往更早」保留，保证可测试、可重放。
    """

    max_recent_messages: int = 50
    max_context_chars: int = 0
    summarize: bool = True
    max_summary_messages: int = 10
    max_summary_chars: int = 4000
