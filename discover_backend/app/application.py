"""应用组装：工厂 + 扩展初始化 + 中间件注册 + 路由挂载。

conftest 依赖 create_app(settings) 做进程内测试隔离（tmp_path 配置）；
main.py 用工厂装配生产实例。与 MODULE_MAP / ARCHITECTURE 的「应用组装在
application.py」对齐（61d67a7 曾删该文件但 conftest 未同步，测试基建损坏，
本次重建）。
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

from fastapi import FastAPI

from app.api.routes_assistants import router as assistants_router
from app.api.routes_chat import router as chat_router
from app.api.routes_files import router as files_router
from app.api.routes_history import router as history_router
from app.config.settings import Settings
from app.container import AppServices
from app.extensions import initialize_extensions
from app.middleware import ExceptionHandlingMiddleware, RequestLoggingMiddleware


class AppLifespan:
    """应用生命周期：启动加载服务，关闭释放资源。"""

    def __init__(self, services: AppServices, app: FastAPI) -> None:
        self._services = services
        self._app = app

    async def __aenter__(self) -> None:
        await self._services.startup(self._app)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._services.shutdown(self._app)


def _make_lifespan(services: AppServices) -> Callable[[FastAPI], AppLifespan]:
    """返回 lifespan 工厂（Starlette 以 callable 形式接收，注入 app）。"""

    def factory(_app: FastAPI) -> AppLifespan:
        return AppLifespan(services, _app)

    return factory


def _register_routes(app: FastAPI) -> None:
    prefix = "/api/v1"
    app.include_router(chat_router, prefix=prefix)
    app.include_router(files_router, prefix=prefix)
    app.include_router(history_router, prefix=prefix)
    app.include_router(assistants_router, prefix=prefix)


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    """挂中间件：异常映射在内层，请求日志在外层（后加者在外）。"""
    app.add_middleware(ExceptionHandlingMiddleware, settings=settings)
    if settings.request_logging_enabled:
        app.add_middleware(RequestLoggingMiddleware)


def create_app(settings: Settings) -> FastAPI:
    """装配应用工厂：服务容器 + 扩展 + 中间件 + 路由。"""
    services = AppServices(settings)
    app = FastAPI(
        title="多智能体承载平台",
        version="0.1.0",
        lifespan=_make_lifespan(services),
    )
    app.state.services = services
    initialize_extensions(app, settings=settings)
    _register_middleware(app, settings)
    _register_routes(app)
    return app
