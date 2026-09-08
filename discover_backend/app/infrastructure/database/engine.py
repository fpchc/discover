"""异步数据库引擎与会话工厂。

SQLAlchemy 2.0 异步接口。应用生命周期内持有单例 Database，服务通过
session_factory 创建 AsyncSession。async 路径内数据库 I/O 全部走异步驱动，
无阻塞（CLAUDE.md §4）。create_async_engine 惰性建连，未配置/未启动
数据库时构造不报错，仅实际 SQL 才触发连接。

连接池：默认 QueuePool（配置驱动，settings.db_pool_*）复用连接——远程库下
每次 DB 操作重建连接是消息保存/历史查询延迟主因；db_pool_size<=0 时退化为
NullPool（每操作即开即关，供跨事件循环的测试/特殊环境回退）。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config.settings import Settings


class Database:
    """数据库句柄：异步引擎 + 会话工厂。由应用生命周期创建 / 关闭。"""

    def __init__(self, settings: Settings) -> None:
        if settings.db_pool_size <= 0:
            self._engine: AsyncEngine = create_async_engine(
                settings.database_url,
                poolclass=NullPool,
                connect_args={"ssl": False},
            )
        else:
            self._engine = create_async_engine(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout_seconds,
                pool_pre_ping=settings.db_pool_pre_ping,
                pool_recycle=settings.db_pool_recycle_seconds,
                connect_args={"ssl": False},
            )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )

    async def dispose(self) -> None:
        """释放连接池（应用关闭时调用）。"""
        await self._engine.dispose()
