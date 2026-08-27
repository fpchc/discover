"""会话历史数据模型（跨边界 DTO，CLAUDE.md §3）。

conversations / messages 持久化载体为 ORM（app/db/models.py），跨边界传递
一律 pydantic BaseModel。usage 为回合聚合（含 prompt 缓存命中/写入）。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ConversationStatus(StrEnum):
    """会话生命周期状态（纯业务状态）。

    软删除不在本枚举——由 ORM Conversation.is_delete 独立标记承载。避免把删除
    塞进业务状态机：删除不再覆盖业务状态（可还原），列表过滤单点 is_delete。
    """

    ACTIVE = "active"
    CLOSED = "closed"


class MessageStatus(StrEnum):
    """回合消息状态。"""

    NORMAL = "normal"
    ERROR = "error"


class TurnUsage(BaseModel):
    """单回合 token 用量（聚合，含 prompt 缓存命中/写入）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_read_tokens: int = 0
    cached_write_tokens: int = 0


class TurnRecord(BaseModel):
    """一回合的落库载荷（路由回合结束时组装，含聚合 usage）。"""

    message_id: str
    query: str
    answer: str | None = None
    thinking: str | None = None
    status: MessageStatus = MessageStatus.NORMAL
    error: str | None = None
    agent_id: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int = 0
    usage: TurnUsage = Field(default_factory=TurnUsage)
    # 仅首回合创建会话行时用作标题；续聊保留原 name 不覆盖
    conversation_name: str = ""


class ConversationRecord(BaseModel):
    """会话记录（历史头部，读取接口返回）。"""

    conversation_id: str
    agent_id: str | None = None
    model_provider: str | None = None
    model_id: str | None = None
    name: str
    summary: str | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE
    dialogue_count: int = 0
    created_at: datetime
    updated_at: datetime


class MessageRecord(BaseModel):
    """回合消息（历史明细，读取接口返回）。"""

    message_id: str
    conversation_id: str
    agent_id: str | None = None
    provider: str | None = None
    model: str | None = None
    query: str
    answer: str | None = None
    thinking: str | None = None
    status: MessageStatus = MessageStatus.NORMAL
    error: str | None = None
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_read_tokens: int = 0
    cached_write_tokens: int = 0
    created_at: datetime
    updated_at: datetime
