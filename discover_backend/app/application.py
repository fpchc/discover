"""FastAPI 应用工厂（L4 接入层）。

生命周期类式实现（__aenter__/__aexit__，禁 asynccontextmanager）。
中间件栈：异常映射在内层（统一错误响应形状），请求日志在外层
（能看到最终状态码）。领域异常映射逻辑见 app/middleware/exceptions.py。
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

from fastapi import FastAPI

from app.api.routes_artifacts import router as artifacts_router
from app.api.routes_chat import router as chat_router
from app.config.settings import Settings, get_settings
from app.container import AppServices
from app.middleware import ExceptionHandlingMiddleware, RequestLoggingMiddleware


class AppLifespan:
    """应用生命周期：启动加载服务，关闭释放资源。"""

    def __init__(self, services: AppServices) -> None:
        self._services = services

    async def __aenter__(self) -> None:
        await self._services.startup()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._services.shutdown()


def create_app(settings: Settings | None = None) -> FastAPI:
    """构建应用。测试可注入 Settings 覆盖路径与开关。"""
    settings = settings or get_settings()
    services = AppServices(settings)
    app = FastAPI(
        title="多智能体承载平台",
        version="0.1.0",
        lifespan=_make_lifespan(services),
    )
    app.state.services = services
    _register_middleware(app, settings)
    _register_routes(app)
    return app


def _make_lifespan(services: AppServices) -> Callable[[FastAPI], AppLifespan]:
    """返回 lifespan 工厂（Starlette 以 callable 形式接收）。"""

    def factory(_app: FastAPI) -> AppLifespan:
        return AppLifespan(services)

    return factory


def _register_routes(app: FastAPI) -> None:
    prefix = "/api/v1"
    app.include_router(chat_router, prefix=prefix)
    app.include_router(artifacts_router, prefix=prefix)


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    """挂中间件：异常映射在内层，请求日志在外层（后加者在外）。"""
    app.add_middleware(ExceptionHandlingMiddleware, settings=settings)
    if settings.request_logging_enabled:
        app.add_middleware(RequestLoggingMiddleware)
