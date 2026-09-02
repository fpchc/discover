"""扩展加载器（bootstrap）：有序加载 + 统一生命周期（模块式可插拔扩展模式）。

本模块只做「组装」：EXTENSIONS 元组引用各能力的访问器模块（实现已归位
infrastructure / capabilities）。新增扩展：写访问器模块 + 在本元组按序追加。
active_settings / set_active_settings 见 app.config.settings。
"""

from __future__ import annotations

from typing import Protocol, cast

from fastapi import FastAPI

from app.capabilities.llm import accessors as ext_llm
from app.capabilities.mcp import accessors as ext_mcp
from app.config.settings import Settings, get_settings, set_active_settings
from app.infrastructure.database import accessors as ext_database
from app.infrastructure.logging import accessors as ext_logging
from app.infrastructure.redis import client as ext_redis
from app.infrastructure.storage import accessors as ext_storage


class Extension(Protocol):
    """扩展模块统一接口。"""

    def is_enabled(self) -> bool: ...

    def init_app(self, app: FastAPI | None) -> None: ...

    async def startup(self, app: FastAPI) -> None: ...

    async def shutdown(self, app: FastAPI) -> None: ...


# 启动顺序即注册顺序；模块对象经 cast 收窄为扩展协议（边界 pragma）。
EXTENSIONS: tuple[Extension, ...] = (
    cast(Extension, ext_logging),
    cast(Extension, ext_database),
    cast(Extension, ext_storage),
    cast(Extension, ext_redis),
    cast(Extension, ext_mcp),
    cast(Extension, ext_llm),
)


def initialize_extensions(app: FastAPI, *, settings: Settings | None = None) -> None:
    """注入配置、按序加载启用扩展（init_app），enabled 列表挂 app.state。"""
    settings = settings or get_settings()
    set_active_settings(settings)
    app.state.settings = settings
    enabled: list[Extension] = []
    for ext in EXTENSIONS:
        if not ext.is_enabled():
            continue
        ext.init_app(app)
        enabled.append(ext)
    app.state.enabled_extensions = enabled


async def startup_extensions(app: FastAPI) -> None:
    """按启用顺序异步启动扩展。"""
    for ext in app.state.enabled_extensions:
        await ext.startup(app)


async def shutdown_extensions(app: FastAPI) -> None:
    """逆序异步关闭扩展。"""
    for ext in reversed(app.state.enabled_extensions):
        await ext.shutdown(app)
