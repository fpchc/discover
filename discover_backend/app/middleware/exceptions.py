"""全局异常中间件：统一错误响应形状 + 服务端 traceback。

PlatformError → http_status_for 状态码 + 脱敏错误体；其他 Exception → 500。
SSE 流内异常由路由自行处理（响应头已发出，中间件无法拦截）。

替代原 application.py 内联 @app.exception_handler，单一实现。
"""

from __future__ import annotations

from logging import getLogger

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config.settings import Settings
from app.errors.base import PlatformError, http_status_for
from app.protocol.sanitize import sanitize_error_message

_LOGGER = getLogger(__name__)


class ExceptionHandlingMiddleware(BaseHTTPMiddleware):
    """把领域异常映射为 HTTP 错误体，兜底未捕获异常为 500。"""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except PlatformError as exc:
            _LOGGER.warning(
                "领域异常：%s %s -> %s", request.method, request.url.path, exc.category.value
            )
            return JSONResponse(
                status_code=http_status_for(exc.category),
                content={
                    "error": {
                        "category": exc.category.value,
                        "message": sanitize_error_message(
                            str(exc), max_length=self._settings.error_message_max_chars
                        ),
                    }
                },
            )
        except Exception:
            _LOGGER.exception("未捕获异常：%s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"error": {"category": "server", "message": "内部错误"}},
            )
