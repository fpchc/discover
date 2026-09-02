"""ORM 模型（持久化载体）。

设计：Blob Engine 模式——文件字节流入存储层（storage/），业务元数据
100% 入库（upload_files）；去重历史入 dedup_clues；对话历史入
conversations（会话头）+ messages（回合明细）。ORM 与 pydantic DTO
分离（CLAUDE.md §3），跨边界传递用 DTO，持久化用 ORM。

账号体系（2026-08-28）：accounts 表按用户 DDL（uuid PK + gen_random_uuid
默认值、username 唯一索引、is_system 标注超级用户）；既有表以 from_account_id /
created_by（varchar(36) 存 uuid 文本）关联账号。账号 ID 在领域层一律用
str(uuid.UUID) 虚线形式（36 字符）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, local_now

# 系统遗留账号（迁移回填既有数据归属；is_system=true 标注超级用户）
SYSTEM_ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


class Account(Base):
    """登录账号（accounts 表，用户 DDL 2026-08-28）。

    密码存 Argon2id PHC 自含编码串（含算法/参数/盐/哈希，无需单独盐列）。
    is_system=true 标注超级用户（可访问管理接口，如全量用量列表）。
    """

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    avatar: Mapped[str | None] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    last_login_ip: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active")
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=local_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=local_now)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=local_now)
    username: Mapped[str] = mapped_column(String(64), default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # 登录来源标记：password（手机号+密码）/ elecnest（公司统一登录）
    user_type: Mapped[str] = mapped_column(String(16), default="password")
    # 公司统一登录体系的主键 id（对方 uid，Long 的数字串），幂等登录唯一键
    elecnest_uid: Mapped[str | None] = mapped_column(String(64))

    # 索引名与用户 DDL 对齐（迁移已按此手写建表）
    __table_args__ = (
        Index("account_phone_idx", "phone"),
        Index("accounts_username_index", "username", unique=True),
        Index("accounts_elecnest_uid_index", "elecnest_uid", unique=True),
    )


class Conversation(Base):
    """会话记录（历史头部）。

    conversation_id 即现有 session_id（API 契约已称 conversation_id）。
    行由 ConversationService.record_turn 内部 upsert 维护；agent_id /
    provider / model 为路由与推理生效后的快照。
    """

    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid4 hex
    # 归属账号（accounts.id 的 uuid 文本）；会话隔离与 token 审计按此过滤
    from_account_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), index=True)
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    # 软删除独立标记：与业务状态 status 解耦（DELETED 不再占用 status 枚举值），
    # 删除不覆盖业务状态，行与 messages 保留（token 可审计）。
    is_delete: Mapped[bool] = mapped_column(default=False)
    dialogue_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=local_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=local_now)


class Message(Base):
    """回合消息（历史明细：query + answer + thinking 一行，usage 聚合到回合）。

    技术债：单行拍平耦合「一问一答」范式，工具调用明细不落库——演进方向
    见 .ai/ARCHITECTURE.md（role-based 消息流 / 事件溯源）。
    """

    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid4 hex
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    # 归属账号（免 join 直接按账号聚合 token 用量）
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), index=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(64))
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    thinking: Mapped[str | None] = mapped_column(Text)  # 审计内容，不进模型上下文
    status: Mapped[str] = mapped_column(String(16), default="normal")
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(default=0)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    total_tokens: Mapped[int] = mapped_column(default=0)
    cached_read_tokens: Mapped[int] = mapped_column(default=0)
    cached_write_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=local_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=local_now)


class UploadFileRecord(Base):
    """文件元数据（多消费方共享注册表：agent 产物 / 知识库等，不强绑定）。

    字节流在存储层，业务元数据全部入库；used 标记文件是否被使用（下载/被消费
    置 true），供后续清理任务回收未使用文件；created_by_role 区分消费方。
    """

    __tablename__ = "upload_files"

    file_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid4 hex
    storage_type: Mapped[str] = mapped_column(String(16), default="local")
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)  # {uuid}.{ext}
    name: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(64), default="")
    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    hash: Mapped[str | None] = mapped_column(String(128))
    # 归属账号（会话产物由会话账号自然携带）；created_by_role 仍区分 agent/user 消费方
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    created_by_role: Mapped[str] = mapped_column(String(32))
    used: Mapped[bool] = mapped_column(default=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=local_now)


class DedupClue(Base):
    """推荐历史线索（去重历史持久化，按账号隔离）。

    组合主键 (created_by, clue_id)：不同账号同日同产品可生成相同 clue_id 而不冲突；
    去重逻辑只注入当前账号的线索（load_history(account_id)）。
    """

    __tablename__ = "dedup_clues"

    # 先声明 created_by，主键列序即 (created_by, clue_id)
    created_by: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    clue_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    product_keywords: Mapped[list[str]] = mapped_column(JSONB)
    target_industry: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=local_now)
    report_path: Mapped[str] = mapped_column(Text, default="")
    recommendations: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    excluded_companies: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    total_found: Mapped[int] = mapped_column(default=0)
    remaining_pool: Mapped[int] = mapped_column(default=0)
