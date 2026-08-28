"""账号认证数据模型（跨边界 DTO，CLAUDE.md §3）。

账号 ID 在领域层一律用 str(uuid.UUID) 虚线形式（36 字符）；持久化 ORM 见
app/db/models.py 的 Account（id 为原生 uuid 类型）。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AccountStatus(StrEnum):
    """账号生命周期状态（DDL 默认 active）。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class LoginRequest(BaseModel):
    """登录请求体（手机号 + 密码）。"""

    phone: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class LoginResponse(BaseModel):
    """登录响应：account_id + JWT + 显示名。"""

    account_id: str
    token: str
    name: str | None = None


class AccountRecord(BaseModel):
    """账号记录（读取接口返回；password_hash 永不外泄）。"""

    account_id: str
    name: str
    phone: str
    avatar: str | None = None
    status: AccountStatus = AccountStatus.ACTIVE
    is_system: bool = False
    created_at: datetime
    last_login_at: datetime | None = None


class UserUsage(BaseModel):
    """账号 token 用量（聚合 messages.created_by 的回合用量）。

    平铺字段便于前端直接消费；conversation_count 为去重后的会话数。
    """

    account_id: str
    name: str
    conversation_count: int = 0
    message_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_read_tokens: int = 0
    cached_write_tokens: int = 0
