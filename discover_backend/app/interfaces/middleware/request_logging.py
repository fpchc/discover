"""请求日志中间件：记录 method/path/status/耗时/client_ip，回写 X-Request-Id。

结构化字段经标准 logging extra 注入记录，由日志扩展的 text/json 格式器统一
呈现；同时把 request_id 写入 trace 上下文（app.infrastructure.logging.logging），使本请求
内所有日志携带同一 trace_id。异常已被内层异常中间件转为响应，此处以
finally 兜底框架级 BaseException（取消等）也记录。
"""

from __future__ import annotations

import time
import uuid
from logging import getLogger

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.infrastructure.logging.logging import set_trace_id

_LOGGER = getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """HTTP 请求日志 + X-Request-Id 响应头。"""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        set_trace_id(request_id)
        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            status_code = response.status_code if response is not None else 500
            _LOGGER.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": round(duration_ms, 1),
                    "client_ip": _client_ip(request),
                    "user_agent": request.headers.get("user-agent", ""),
                },
            )
            if response is not None:
                response.headers.setdefault("X-Request-Id", request_id)


def _client_ip(request: Request) -> str:
    """客户端地址；无连接信息（如内部调用）时为空串。"""
    return request.client.host if request.client is not None else ""
