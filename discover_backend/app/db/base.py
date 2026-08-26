"""SQLAlchemy 声明式基类与命名约定。

所有 ORM 模型继承 Base；命名约定统一约束/索引名，便于 Alembic 生成
可读迁移。ORM 模型只负责持久化，跨边界 DTO / 事件仍是 pydantic
（CLAUDE.md §3），两者不混用。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """ORM 声明式基类。"""

    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


def local_now() -> datetime:
    return datetime.now()
