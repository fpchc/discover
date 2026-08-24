"""FastAPI 应用工厂（L4 接入层）。

生命周期类式实现（__aenter__/__aexit__，禁 asynccontextmanager）。
异常处理器把领域异常映射为 HTTP 状态与脱敏错误体。
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from platform_engine.api.deps import AppServices
from platform_engine.api.routes_artifacts import router as artifacts_router
from platform_engine.api.routes_chat import router as chat_router
from platform_engine.config.settings import Settings, get_settings
from platform_engine.errors.base import ErrorCategory, PlatformError
from platform_engine.protocol.sanitize import sanitize_error_message


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
    _register_exception_handlers(app, settings)
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


def _register_exception_handlers(app: FastAPI, settings: Settings) -> None:
    @app.exception_handler(PlatformError)
    async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc.category),
            content={
                "error": {
                    "category": exc.category.value,
                    "message": sanitize_error_message(
                        str(exc), max_length=settings.error_message_max_chars
                    ),
                }
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"category": "server", "message": "内部错误"}},
        )


def _status_for(category: ErrorCategory) -> int:
    mapping = {
        ErrorCategory.NOT_FOUND: 404,
        ErrorCategory.INVALID_ARGUMENT: 400,
        ErrorCategory.AUTH: 401,
        ErrorCategory.DENIED: 403,
        ErrorCategory.BAD_REQUEST: 400,
        ErrorCategory.CONFIG: 500,
    }
    return mapping.get(category, 500)


def main() -> None:
    """入口：uvicorn 启动（host/port 配置驱动）。"""
    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
