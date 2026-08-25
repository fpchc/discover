"""ORM 模型（持久化载体）。

设计：Blob Engine 模式——文件字节流入存储层（storage/），业务元数据
100% 入库（upload_files）；去重历史入 dedup_clues。ORM 与 pydantic DTO
分离（CLAUDE.md §3），跨边界传递用 DTO，持久化用 ORM。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utc_now


class UploadFileRecord(Base):
    """文件元数据（字节流在存储层，业务元数据全部入库）。"""

    __tablename__ = "upload_files"

    file_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid4 hex
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)  # {uuid}.{ext}
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DedupClue(Base):
    """推荐历史线索（去重历史持久化，跨会话共享）。"""

    __tablename__ = "dedup_clues"

    clue_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    product_keywords: Mapped[list[str]] = mapped_column(JSONB)
    target_industry: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    report_path: Mapped[str] = mapped_column(Text, default="")
    recommendations: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    excluded_companies: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    total_found: Mapped[int] = mapped_column(default=0)
    remaining_pool: Mapped[int] = mapped_column(default=0)
