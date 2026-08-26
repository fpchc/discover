"""会话层数据模型（跨边界对象一律 pydantic，CLAUDE.md §3）。

会话记录、产物记录在会话生命周期内跨模块传递，必须为 pydantic
BaseModel。纯内部运行句柄（工作区、下载句柄）见 workspace.py /
service.py 的 @dataclass（带 pragma 标注）。
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.catalog.models import AssistantTarget


def utc_now() -> datetime:
    """时区感知的当前 UTC 时间（会话各时间戳统一入口）。"""
    return datetime.now(UTC)


class SessionStatus(StrEnum):
    """会话生命周期状态。"""

    ACTIVE = "active"
    CLOSED = "closed"


class SessionRecord(BaseModel):
    """会话记录。会话 ID 由服务端生成（uuid4），不可猜测。

    绑定的是「助手目标」（assistant_target：type + id），而非裸 agent_id——
    未来通用 / 简单技能都是独立目标，随状态自然增长（skill_id 预留显式技能选择）。
    """

    session_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    assistant_target: AssistantTarget | None = None
    skill_id: str | None = None
    status: SessionStatus = SessionStatus.ACTIVE


class ArtifactRecord(BaseModel):
    """产物记录（跨边界 DTO）。字节在存储层，元数据据此对外暴露。

    文件注册表多消费方共享、不强绑定会话/智能体（用户决策），故 DTO 不含
    session_id/agent_id。
    """

    artifact_id: str
    filename: str
    media_type: str
    size_bytes: int
    created_at: datetime = Field(default_factory=utc_now)
