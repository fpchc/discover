"""db 插件：封装现有 Database（SQLAlchemy 异步引擎 + 会话工厂）。

引擎惰性建连（与现状一致）：startup 无操作，首次 SQL 才建立连接，
未配置 / 未启动数据库不阻塞应用启动。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.db.engine import Database
from app.plugins.base import Plugin, register


@register
class DBPlugin(Plugin):
    """PostgreSQL 异步引擎 + 会话工厂。"""

    name = "db"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._db = Database(settings)

    @classmethod
    def is_enabled(cls, settings: Settings) -> bool:
        return settings.db_enabled

    @property
    def client(self) -> Database:
        return self._db

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._db.session_factory

    async def startup(self) -> None:
        """惰性建连：无操作。"""

    async def shutdown(self) -> None:
        await self._db.dispose()
