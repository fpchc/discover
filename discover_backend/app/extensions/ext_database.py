"""数据库扩展：PostgreSQL 异步引擎 + 会话工厂。

引擎惰性建连（与现状一致）：startup 无操作，首次 SQL 才建立连接，
未配置 / 未启动数据库不阻塞应用启动。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.db.engine import Database
from app.extensions.base import active_settings

_database: Database | None = None


def is_enabled() -> bool:
    """由配置开关控制。"""
    return active_settings().db_enabled


def init_app(app: FastAPI | None) -> None:
    """构造惰性数据库句柄。"""
    global _database
    _database = Database(active_settings())


async def startup(app: FastAPI) -> None:
    """惰性建连：无操作。"""


async def shutdown(app: FastAPI) -> None:
    """释放连接池。"""
    global _database
    if _database is not None:
        await _database.dispose()
        _database = None


def get_database() -> Database:
    """取数据库客户端；扩展未启用或未初始化时抛断言。"""
    assert _database is not None
    return _database
