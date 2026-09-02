"""会话历史数据模型（跨边界 DTO，CLAUDE.md §3）。

conversations / messages 持久化载体为 ORM（app/db/models.py），跨边界传递
一律 pydantic BaseModel。usage 为回合聚合（含 prompt 缓存命中/写入）。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.assistant.models import AssistantTarget, TargetType


class ConversationStatus(StrEnum):
    """会话生命周期状态（纯业务状态）。

    软删除不在本枚举——由 ORM Conversation.is_delete 独立标记承载。避免把删除
    塞进业务状态机：删除不再覆盖业务状态（可还原），列表过滤单点 is_delete。
    """

    ACTIVE = "active"
    CLOSED = "closed"


class MessageStatus(StrEnum):
    """回合消息状态：normal 正常完成 / error 服务端失败 / interrupted 客户端中断。

    interrupted 用于流式回合被客户端断开/取消但已产生部分内容的情形——仍有
    记录可查（query + partial answer），只是未完整走完。
    """

    NORMAL = "normal"
    ERROR = "error"
    INTERRUPTED = "interrupted"


class TurnUsage(BaseModel):
    """单回合 token 用量（聚合，含 prompt 缓存命中/写入）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_read_tokens: int = 0
    cached_write_tokens: int = 0


class TurnRecord(BaseModel):
    """一回合的落库载荷（路由回合结束时组装，含聚合 usage）。

    account_id 为回合归属账号（会话 from_account_id 与消息 created_by 同源）；
    落库时由 ConversationService 分别写入 conversations.from_account_id 与
    messages.created_by。
    """

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
    # 归属账号（uuid 文本，来自会话创建者）
    account_id: str = ""


class UsageAggregate(BaseModel):
    """账号 token 用量聚合（messages.created_by 维度；AuthService 组装 UserUsage）。"""

    conversation_count: int = 0
    message_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_read_tokens: int = 0
    cached_write_tokens: int = 0


class DailyUsageItem(BaseModel):
    """单日 token 用量（趋势图单点；口径与 UsageAggregate 一致，多出日期维度）。

    前端图显换算：输入未命中 = prompt_tokens - cached_read_tokens；
    输入命中 = cached_read_tokens；输出 = completion_tokens；x 轴取 date(MM-DD)。
    """

    date: date
    conversation_count: int = 0
    message_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_read_tokens: int = 0
    cached_write_tokens: int = 0


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


class ConversationSession(BaseModel):
    """对话记录解析结果（resolve 返回）：会话身份 + 归属账号 + 助手绑定。

    对话记录唯一事实来源为 DB conversations 行（app/db/models.py）；本 DTO
    供路由透传 streaming/blocking/persist 与图运行时（assistant_target）。
    """

    conversation_id: str
    account_id: str
    assistant_target: AssistantTarget | None = None

    @property
    def assistant_meta(self) -> dict[str, str | None] | None:
        """响应元数据中的 assistant 信息（type + id）；无绑定 → None。"""
        if self.assistant_target is None:
            return None
        return {"type": self.assistant_target.type.value, "id": self.assistant_target.id}

    @property
    def agent_id_label(self) -> str | None:
        """历史落库 agent 标签：expert 取 id；其余（通用/未绑定）None。"""
        target = self.assistant_target
        if target is None or target.type != TargetType.EXPERT:
            return None
        return target.id


class MessageRecord(BaseModel):
    """回合消息（历史明细，读取接口返回）。

    对外不下发 token 用量与 provider/model（内部审计维度）：读取接口只暴露
    业务可见字段；provider/model/usage 仅存在于落库载荷 TurnRecord，供审计/计费。
    """

    message_id: str
    conversation_id: str
    agent_id: str | None = None
    query: str
    answer: str | None = None
    thinking: str | None = None
    status: MessageStatus = MessageStatus.NORMAL
    error: str | None = None
    latency_ms: int = 0
    created_at: datetime
    updated_at: datetime
