"""ORM 模型（持久化载体）。

设计：Blob Engine 模式——文件字节流入存储层（storage/），业务元数据
100% 入库（upload_files）；去重历史入 dedup_clues；对话历史入
conversations（会话头）+ messages（回合明细）。ORM 与 pydantic DTO
分离（CLAUDE.md §3），跨边界传递用 DTO，持久化用 ORM。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, local_now


class Conversation(Base):
    """会话记录（历史头部）。

    conversation_id 即现有 session_id（API 契约已称 conversation_id）。
    行由 ConversationService.record_turn 内部 upsert 维护；agent_id /
    provider / model 为路由与推理生效后的快照。
    """

    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid4 hex
    agent_id: Mapped[str | None] = mapped_column(String(64), index=True)
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
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
    created_by_role: Mapped[str] = mapped_column(String(32))
    used: Mapped[bool] = mapped_column(default=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=local_now)


class DedupClue(Base):
    """推荐历史线索（去重历史持久化，跨会话共享）。"""

    __tablename__ = "dedup_clues"

    clue_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    product_keywords: Mapped[list[str]] = mapped_column(JSONB)
    target_industry: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=local_now)
    report_path: Mapped[str] = mapped_column(Text, default="")
    recommendations: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    excluded_companies: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    total_found: Mapped[int] = mapped_column(default=0)
    remaining_pool: Mapped[int] = mapped_column(default=0)
