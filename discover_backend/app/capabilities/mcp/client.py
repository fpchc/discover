"""远程 MCP 客户端（Streamable HTTP，httpx 直连，禁用 SDK）。

协议：JSON-RPC over Streamable HTTP。初始化握手获取会话标识，随后
list_tools / call_tool。响应可能是 application/json 或 text/event-stream，
统一解析。认证令牌从环境读取，值不落配置不落代码。
"""

from __future__ import annotations

import json
import logging
import time
from itertools import count
from types import TracebackType
from typing import Any

import anyio
import httpx
from pydantic import BaseModel, Field

from app.config.loader import MCPServer
from app.config.settings import Settings
from app.shared.errors.base import (
    MCPAuthError,
    MCPConnectionError,
    MCPInvalidArgumentError,
    MCPRateLimitError,
    MCPServiceError,
    MCPTimeoutError,
)

_PROTOCOL_VERSION = "2025-03-26"
_CLIENT_NAME = "agent-platform"
_CLIENT_VERSION = "0.1.0"
_JSON_RPC_INVALID_PARAMS = -32602
_ACCEPT_HEADER = "application/json, text/event-stream"

logger = logging.getLogger(__name__)


class MCPToolInfo(BaseModel):
    """MCP 服务声明的工具（以 list_tools 结果为准，不假定结构）。"""

    name: str
    description: str = ""
    input_schema: dict[str, object] = Field(default_factory=dict)


class MCPCallResult(BaseModel):
    """MCP 工具调用结果。is_error 表示工具级执行失败。"""

    content: str
    is_error: bool = False


def _extract_text(content: object) -> str:
    """从 MCP 结果 content 数组提取 text 段拼接。"""
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _last_sse_data(text: str) -> str | None:
    """从 SSE 文本取最后一个 data: 负载。"""
    data_lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    return data_lines[-1] if data_lines else None


class MCPClient:
    """单个 MCP 服务的 JSON-RPC 客户端。进程级复用，类式异步生命周期。"""

    def __init__(
        self,
        server: MCPServer,
        settings: Settings,
        *,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._server = server
        self._api_key = api_key
        self._http = http_client
        self._session_id: str | None = None
        self._ids = count(1)

    @property
    def call_timeout_seconds(self) -> float:
        return self._server.call_timeout_seconds

    async def __aenter__(self) -> MCPClient:
        if self._http is None:
            self._http = self._build_http()
        await self._initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _build_http(self) -> httpx.AsyncClient:
        handshake = self._server.handshake_timeout_seconds
        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=handshake,
                read=self._server.call_timeout_seconds,
                write=handshake,
                pool=handshake,
            )
        )

    def _require_http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("MCPClient 尚未进入生命周期（__aenter__）")
        return self._http

    # ---- 握手 ----
    async def _initialize(self) -> None:
        logger.debug("MCP 握手开始：server=%s url=%s", self._server.id, self._server.base_url)
        params: dict[str, object] = {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": _CLIENT_NAME, "version": _CLIENT_VERSION},
        }
        payload: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "initialize",
            "params": params,
        }
        response = await self._post(payload)
        header = response.headers.get("mcp-session-id")
        body = await self._parse_body(response)
        result = body.get("result")
        if header:
            self._session_id = header
        elif isinstance(result, dict):
            session = result.get("sessionId")
            if isinstance(session, str):
                self._session_id = session
        await self._notify("notifications/initialized", {})
        logger.debug(
            "MCP 握手完成：server=%s session=%s",
            self._server.id,
            "已获取" if self._session_id else "服务端无会话态",
        )

    async def _notify(self, method: str, params: dict[str, object]) -> None:
        """发送不需要响应的 JSON-RPC 通知。"""
        payload: dict[str, object] = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._post(payload)

    # ---- 协议方法 ----
    async def list_tools(self) -> list[MCPToolInfo]:
        result = await self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise MCPServiceError("MCP list_tools 返回格式非法")
        infos: list[MCPToolInfo] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            infos.append(
                MCPToolInfo(
                    name=str(tool.get("name", "")),
                    description=str(tool.get("description", "")),
                    input_schema=_as_dict(tool.get("inputSchema")),
                )
            )
        logger.debug("MCP 工具列表：server=%s 工具数=%d", self._server.id, len(infos))
        return infos

    async def call_tool(self, name: str, arguments: dict[str, object]) -> MCPCallResult:
        logger.debug("MCP 调用工具：server=%s tool=%s", self._server.id, name)
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        is_error = bool(result.get("isError", False))
        call_result = MCPCallResult(content=_extract_text(result.get("content")), is_error=is_error)
        logger.debug(
            "MCP 工具调用完成：server=%s tool=%s is_error=%s 结果长度=%d",
            self._server.id,
            name,
            call_result.is_error,
            len(call_result.content),
        )
        return call_result

    # ---- 传输 ----
    async def _request_raw(self, method: str, params: dict[str, object]) -> dict[str, object]:
        """发起 JSON-RPC 请求并返回完整响应体（可能含 error 键）。"""
        payload: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
            "params": params,
        }
        response = await self._post(payload)
        body = await self._parse_body(response)
        return body

    async def _request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        body = await self._request_raw(method, params)
        error = body.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = str(error.get("message", "未知错误"))
            if code == _JSON_RPC_INVALID_PARAMS:
                raise MCPInvalidArgumentError(f"MCP 参数非法：{message}")
            raise MCPServiceError(f"MCP 服务错误：{message}")
        result = body.get("result")
        return result if isinstance(result, dict) else {}

    async def _post(self, payload: dict[str, object]) -> httpx.Response:
        http = self._require_http()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": _ACCEPT_HEADER,
            "Content-Type": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        url = self._server.base_url.rstrip("/")
        method = str(payload.get("method", "-"))
        msg_id = payload.get("id")
        logger.debug("MCP 请求发出：server=%s method=%s id=%s", self._server.id, method, msg_id)
        started = time.monotonic()
        try:
            with anyio.fail_after(self._server.call_timeout_seconds):
                response = await http.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning(
                "MCP 请求超时：server=%s method=%s id=%s", self._server.id, method, msg_id
            )
            raise MCPTimeoutError("调用 MCP 服务超时") from exc
        except httpx.RequestError as exc:
            logger.warning(
                "MCP 连接失败：server=%s method=%s id=%s", self._server.id, method, msg_id
            )
            raise MCPConnectionError("连接 MCP 服务失败") from exc
        except TimeoutError as exc:
            logger.warning(
                "MCP 请求超时：server=%s method=%s id=%s", self._server.id, method, msg_id
            )
            raise MCPTimeoutError("调用 MCP 服务超时") from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.debug(
            "MCP 响应：server=%s method=%s id=%s status=%d content-type=%s %dms",
            self._server.id,
            method,
            msg_id,
            response.status_code,
            response.headers.get("content-type", ""),
            elapsed_ms,
        )
        return response

    async def _parse_body(self, response: httpx.Response) -> dict[str, object]:
        await self._raise_for_status(response)
        text = (await response.aread()).decode("utf-8", errors="replace")
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            data = _last_sse_data(text)
            if data is None:
                return {}
            text = data
        try:
            parsed: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MCPServiceError("MCP 响应不是合法 JSON") from exc
        if not isinstance(parsed, dict):
            return {}
        return parsed

    async def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        if response.status_code in (401, 403):
            raise MCPAuthError(f"MCP 认证失败（HTTP {response.status_code}）")
        if response.status_code == 429:
            raise MCPRateLimitError("MCP 上游限流（HTTP 429）")
        if response.status_code == 400:
            raise MCPInvalidArgumentError("MCP 请求非法（HTTP 400）")
        raise MCPServiceError(f"MCP 服务端错误（HTTP {response.status_code}）")


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}
