"""扩展包：有序加载 + 统一生命周期（模块式可插拔扩展模式）。

每个扩展 = 一个模块（ext_*.py），暴露 is_enabled() / init_app(app) /
startup(app) / shutdown(app)。EXTENSIONS 元组为启动顺序（logging 必须最先，
保证统一日志先配置）；关停逆序。新增扩展：写 ext_*.py + 在 EXTENSIONS
按序追加。
"""

from __future__ import annotations

from typing import Protocol, cast

from fastapi import FastAPI

from app.config.settings import Settings, get_settings
from app.extensions import ext_database, ext_llm, ext_logging, ext_mcp, ext_redis, ext_storage
from app.extensions.base import set_active_settings


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
