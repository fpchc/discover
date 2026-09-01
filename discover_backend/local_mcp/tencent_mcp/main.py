"""腾讯联网搜索 MCP 服务（Streamable HTTP）：把腾讯 WSA SearchPro 暴露为标准 MCP 工具。

平台（app/tools/mcp_client.py）作为 MCP 客户端经 streamable_http 连接本服务：
initialize 握手 → tools/list 发现工具 → tools/call 调用，Bearer 令牌校验（fail-closed）。
运行：python -m local_mcp.tencent_mcp.main（默认 127.0.0.1:10001/mcp）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import (
    asynccontextmanager,  # noqa: TID251  # pragma: 简化 — FastAPI lifespan 需 async 生成器签名
)
from types import TracebackType
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response

from local_mcp.tencent_mcp.providers import (
    SearchProvider,
    SearchServiceError,
    TencentSearchProvider,
)
from local_mcp.tencent_mcp.settings import TencentMCPSettings

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "tencent-search-mcp"
SERVER_VERSION = "0.1.0"

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "web_search_tencent",
        "description": "腾讯联网搜索（WSA）：输入关键词，返回网页标题、摘要、链接与发布时间",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索关键词"}},
            "required": ["query"],
        },
    },
]


def _provider_factories(settings: TencentMCPSettings) -> dict[str, SearchProvider]:
    return {"web_search_tencent": TencentSearchProvider(settings)}


class TencentMcpLifespan:
    """类式生命周期：启动进入提供方（建 httpx 客户端），关闭释放。"""

    def __init__(self, providers: dict[str, SearchProvider]) -> None:
        self._providers = providers
        self._initialized = False

    async def __aenter__(self) -> None:
        """异步上下文管理器进入时初始化所有 provider。"""
        if self._initialized:
            return
        for name, provider in self._providers.items():
            try:
                await provider.__aenter__()
                logger.info(f"Provider {name} initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize provider {name}: {e}")
                raise
        self._initialized = True

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """异步上下文管理器退出时释放所有 provider。"""
        if not self._initialized:
            return
        for name, provider in self._providers.items():
            try:
                await provider.__aexit__(exc_type, exc_value, traceback)
                logger.info(f"Provider {name} closed successfully")
            except Exception as e:
                logger.warning(f"Error closing provider {name}: {e}")
        self._initialized = False


@asynccontextmanager
async def _lifespan_factory(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI 生命周期管理。"""
    providers: dict[str, SearchProvider] = app.state.providers
    lifespan = TencentMcpLifespan(providers)
    async with lifespan:
        yield


# ---- MCP JSON-RPC 响应构造 ----
def _jsonrpc_result(
    msg_id: int | str | None, result: dict[str, Any], *, session_id: str | None = None
) -> Response:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "result": result}
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return Response(
        content=json.dumps(body, ensure_ascii=False),
        media_type="application/json",
        headers=headers,
    )


def _jsonrpc_error(msg_id: int | str | None, code: int, message: str) -> Response:
    body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }
    return Response(
        content=json.dumps(body, ensure_ascii=False),
        media_type="application/json",
        status_code=200,  # JSON-RPC 错误返回 200
    )


def _call_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _authorize(request: Request, settings: TencentMCPSettings) -> None:
    """Bearer 令牌校验，fail-closed。"""
    token = settings.tencent_mcp_token
    if not token:
        raise HTTPException(status_code=401, detail="tencent_mcp_token 未配置")
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer 认证头")
    if auth_header[7:] != token:  # 去掉 "Bearer " 前缀
        raise HTTPException(status_code=401, detail="认证失败")


async def _request_json(request: Request) -> dict[str, Any]:
    try:
        payload: Any = await request.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def _handle_tools_call(
    providers: dict[str, SearchProvider], params: dict[str, Any]
) -> dict[str, Any]:
    name = str(params.get("name", ""))
    arguments = params.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}
    query = str(arguments.get("query", "")).strip()
    if not query:
        return _call_result("搜索关键词不能为空", is_error=True)
    provider = providers.get(name)
    if provider is None:
        return _call_result(f"工具不存在：{name}", is_error=True)
    try:
        text = await provider.search(query)
    except SearchServiceError as exc:
        logger.warning(f"Search error for {name}: {exc}")
        return _call_result(str(exc), is_error=True)
    except Exception as exc:
        logger.error(f"Unexpected error for {name}: {exc}", exc_info=True)
        return _call_result(f"搜索服务异常：{exc}", is_error=True)
    return _call_result(text)


def create_app(
    settings: TencentMCPSettings | None = None,
    *,
    providers: dict[str, SearchProvider] | None = None,
) -> FastAPI:
    """装配腾讯联网搜索 MCP 服务。测试可注入 providers（MockTransport 的 httpx 客户端）。"""
    settings = settings or TencentMCPSettings()
    providers = providers or _provider_factories(settings)

    app = FastAPI(
        title=SERVER_NAME,
        version=SERVER_VERSION,
        lifespan=_lifespan_factory,
    )
    app.state.providers = providers
    app.state.settings = settings

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> Response:
        _authorize(request, settings)

        payload = await _request_json(request)
        method = payload.get("method")
        msg_id = payload.get("id")
        logger.info("MCP 请求", extra={"method": method, "msg_id": msg_id})

        # 处理 initialize
        if method == "initialize":
            sid = str(uuid4())
            return _jsonrpc_result(
                msg_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "sessionId": sid,
                },
                session_id=sid,
            )

        # 处理 notifications/initialized
        if method == "notifications/initialized":
            return Response(status_code=202)

        # 处理 tools/list
        if method == "tools/list":
            return _jsonrpc_result(msg_id, {"tools": _TOOLS})

        # 处理 tools/call
        if method == "tools/call":
            params = payload.get("params")
            params = params if isinstance(params, dict) else {}
            logger.info(
                "MCP 工具调用入参：msg_id=%s tool=%s params=%s",
                msg_id,
                params.get("name"),
                json.dumps(params, ensure_ascii=False),
            )
            result = await _handle_tools_call(providers, params)
            logger.info(
                "MCP 工具调用返回：msg_id=%s tool=%s result=%s",
                msg_id,
                params.get("name"),
                json.dumps(result, ensure_ascii=False),
            )
            return _jsonrpc_result(msg_id, result)

        # 未知方法
        return _jsonrpc_error(msg_id, -32601, f"方法不存在：{method}")

    @app.get("/")
    async def health() -> dict[str, str]:
        return {"service": SERVER_NAME, "status": "ok"}

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"service": SERVER_NAME, "status": "ok"}

    return app


def main() -> None:
    """服务启动入口。"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    settings = TencentMCPSettings()
    app = create_app(settings)

    logger.info(
        f"Starting {SERVER_NAME} v{SERVER_VERSION} on "
        f"{settings.tencent_mcp_host}:{settings.tencent_mcp_port}"
    )
    logger.info(f"MCP endpoint: http://{settings.tencent_mcp_host}:{settings.tencent_mcp_port}/mcp")

    uvicorn.run(
        app,
        host=settings.tencent_mcp_host,
        port=settings.tencent_mcp_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
