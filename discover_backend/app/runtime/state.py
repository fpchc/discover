"""图状态模型（graph-runtime-spec §3）：pydantic 跨边界传递。

messages / artifacts 用自定义累加器（LangGraph 通道 reducer）实现追加；
其余列表字段按 LangGraph 默认语义整值替换。工作区路径用字符串形式，
节点内转 Path（运行时句柄不跨边界序列化）。
"""

from typing import Annotated

from pydantic import BaseModel, Field

from app.capabilities.llm.models import ChatMessage
from app.capabilities.tools.broker import ToolCallRequest
from app.domain.assistant.models import AssistantTarget
from app.interfaces.schemas.files import ArtifactRecord


def _append_messages(left: list[ChatMessage], right: list[ChatMessage]) -> list[ChatMessage]:
    return left + right


def _append_artifacts(
    left: list[ArtifactRecord], right: list[ArtifactRecord]
) -> list[ArtifactRecord]:
    return left + right


class GateStatus(BaseModel):
    """门禁执行状态（§6）：通过标志 + 失败项 + 检查轮次。"""

    passed: bool
    failures: list[str] = Field(default_factory=list)
    turn: int = 0


class GraphState(BaseModel):
    """图运行时状态。跨边界传递，工作区用字符串路径。"""

    messages: Annotated[list[ChatMessage], _append_messages] = Field(default_factory=list)
    artifacts: Annotated[list[ArtifactRecord], _append_artifacts] = Field(default_factory=list)
    session_id: str = ""
    workspace_path: str = ""
    input: str = ""
    # 本回合对话记录的助手绑定（resolve 结果，路由传入；assemble 前的解析依据）
    assistant_target: AssistantTarget | None = None
    active_target: AssistantTarget | None = None
    active_skill: str | None = None
    resolve_reason: str | None = None
    loaded_references: set[str] = Field(default_factory=set)
    exposed_tools: list[str] = Field(default_factory=list)
    gate_status: dict[str, GateStatus] = Field(default_factory=dict)
    degraded_sources: list[str] = Field(default_factory=list)
    turn: int = 0
    usage: dict[str, int] = Field(default_factory=dict)
    pending_calls: list[ToolCallRequest] = Field(default_factory=list)
