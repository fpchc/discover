"""进程入口：uvicorn 启动（host/port 配置驱动）。

与 api 接入层解耦：main() 只负责把配置、应用工厂与 uvicorn 粘合起来，
属于进程级职责，不落入 api/ 包。
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

import uvicorn
from fastapi import FastAPI

from app.api.routes_artifacts import router as artifacts_router
from app.api.routes_chat import router as chat_router
from app.config.settings import Settings, get_settings
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
    app.include_router(artifacts_router, prefix=prefix)


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    """挂中间件：异常映射在内层，请求日志在外层（后加者在外）。"""
    app.add_middleware(ExceptionHandlingMiddleware, settings=settings)
    if settings.request_logging_enabled:
        app.add_middleware(RequestLoggingMiddleware)


settings = get_settings()
settings = settings or get_settings()
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

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", host=settings.host, port=settings.port, log_level=settings.log_level.lower()
    )
