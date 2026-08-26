"""中间件单测：全局异常映射 + 请求日志。

进程内 ASGI 请求（httpx.ASGITransport）打到挂了两个中间件的裸 FastAPI
应用：PlatformError → 统一 404 JSON；泛型异常 → 500 JSON 且保留服务端
traceback 日志；正常请求带 X-Request-Id 并产生结构化请求日志。
"""

import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from app.config.settings import Settings
from app.errors.base import ErrorCategory, PlatformError
from app.middleware import ExceptionHandlingMiddleware, RequestLoggingMiddleware
from fastapi import FastAPI


def _make_app() -> FastAPI:
    """裸 FastAPI：挂中间件 + 三个探针路由。"""
    app = FastAPI()
    app.add_middleware(ExceptionHandlingMiddleware, settings=Settings(_env_file=None))
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/nf")
    async def not_found() -> None:
        raise PlatformError("找不到资源", category=ErrorCategory.NOT_FOUND)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture()
async def http() -> AsyncIterator[httpx.AsyncClient]:
    """进程内 ASGI 客户端。"""
    app = _make_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/") as client:
        yield client


async def test_platform_error_mapped_to_json(http: httpx.AsyncClient) -> None:
    response = await http.get("/nf")
    assert response.status_code == 404
    assert response.json() == {"error": {"category": "not_found", "message": "找不到资源"}}


async def test_generic_exception_mapped_with_traceback(
    http: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = await http.get("/boom")
    assert response.status_code == 500
    assert response.json() == {"error": {"category": "server", "message": "内部错误"}}
    assert any(rec.levelno == logging.ERROR and rec.exc_info for rec in caplog.records)


async def test_request_logging_with_request_id(
    http: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        response = await http.get("/ok")
    assert response.status_code == 200
    assert response.headers["x-request-id"]
    records = [rec for rec in caplog.records if rec.name == "app.middleware.request_logging"]
    assert records
    rec = records[-1]
    assert rec.getMessage() == "http_request"
    # 结构化字段经标准 logging extra 注入为记录属性（日志扩展格式器统一呈现）。
    assert rec.method == "GET"
    assert rec.path == "/ok"
    assert rec.status == 200
    assert rec.request_id == response.headers["x-request-id"]
