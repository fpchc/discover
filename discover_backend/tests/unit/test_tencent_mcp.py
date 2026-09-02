"""腾讯联网搜索 MCP 服务测试：提供方解析 + MCP 协议全链路互通 + 鉴权。

全链路用例用平台真实客户端（app.capabilities.mcp.client.MCPClient）经 ASGITransport 连本服务，
验证 Streamable HTTP 握手 / list_tools / call_tool 与平台客户端完全兼容。所有 HTTP
一律 MockTransport，不发真实网络请求。
"""

import json

import httpx
import pytest
from app.capabilities.mcp.client import MCPClient
from app.config.loader import MCPServer, MCPServerAuth
from app.config.settings import Settings
from app.shared.errors.base import MCPAuthError
from local_mcp.tencent_mcp.main import create_app
from local_mcp.tencent_mcp.providers import SearchServiceError, TencentSearchProvider
from local_mcp.tencent_mcp.settings import TencentMCPSettings

MCP_SERVER = MCPServer(
    id="tencent_mcp",
    transport="streamable_http",
    base_url="http://127.0.0.1:10001/mcp",
    auth=MCPServerAuth(token_env="TENCENT_MCP_TOKEN"),
    call_timeout_seconds=30,
    concurrency_limit=3,
)


def _settings(**overrides: object) -> TencentMCPSettings:
    return TencentMCPSettings(_env_file=None, **overrides)


def _tencent_pages_handler(captured: list[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        pages = [
            json.dumps(
                {
                    "title": "T1",
                    "passage": "P1",
                    "url": "u1",
                    "date": "2026-08-01",
                    "site": "网易",
                },
                ensure_ascii=False,
            )
        ]
        return httpx.Response(200, json={"Response": {"Pages": pages}})

    return httpx.MockTransport(handler)


# ---- 提供方：腾讯 WSA ----
async def test_tencent_provider_parses_pages() -> None:
    captured: list[dict[str, object]] = []
    settings = _settings(wsa_api_key="k")
    async with TencentSearchProvider(
        settings, http_client=httpx.AsyncClient(transport=_tencent_pages_handler(captured))
    ) as provider:
        text = await provider.search("腾讯云")
    assert captured == [{"Query": "腾讯云"}]
    assert "- T1" in text
    assert "网易  ·  2026-08-01" in text
    assert "P1" in text
    assert "u1" in text


async def test_tencent_provider_business_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "Response": {
                    "Error": {"Code": "InternalError", "Message": "内部错误。"},
                    "RequestId": "req-1",
                }
            },
        )

    settings = _settings(wsa_api_key="k")
    async with TencentSearchProvider(
        settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ) as provider:
        with pytest.raises(SearchServiceError, match="内部错误"):
            await provider.search("腾讯云")


async def test_tencent_provider_missing_key_rejected() -> None:
    async with TencentSearchProvider(_settings()) as provider:
        with pytest.raises(SearchServiceError, match="WSA_API_KEY"):
            await provider.search("腾讯云")


# ---- MCP 协议全链路（平台真实客户端连本地服务）----
async def test_mcp_protocol_full_path_via_platform_client() -> None:
    settings = _settings(tencent_mcp_token="test-token", wsa_api_key="k")
    tencent = TencentSearchProvider(
        settings, http_client=httpx.AsyncClient(transport=_tencent_pages_handler([]))
    )
    app = create_app(settings, providers={"web_search_tencent": tencent})
    client = MCPClient(
        MCP_SERVER,
        Settings(_env_file=None),
        api_key="test-token",
        http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    async with client:
        tools = await client.list_tools()
        assert [t.name for t in tools] == ["web_search_tencent"]
        result = await client.call_tool("web_search_tencent", {"query": "腾讯云"})
        assert result.is_error is False
        assert "- T1" in result.content


async def test_mcp_business_error_surfaces_is_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"Response": {"Error": {"Code": "InternalError", "Message": "内部错误。"}}},
        )

    settings = _settings(tencent_mcp_token="test-token", wsa_api_key="k")
    tencent = TencentSearchProvider(
        settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    app = create_app(settings, providers={"web_search_tencent": tencent})
    client = MCPClient(
        MCP_SERVER,
        Settings(_env_file=None),
        api_key="test-token",
        http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    async with client:
        result = await client.call_tool("web_search_tencent", {"query": "腾讯云"})
    assert result.is_error is True
    assert "内部错误" in result.content


async def test_mcp_auth_rejected_wrong_token() -> None:
    app = create_app(_settings(tencent_mcp_token="right-token"))
    client = MCPClient(
        MCP_SERVER,
        Settings(_env_file=None),
        api_key="wrong-token",
        http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    with pytest.raises(MCPAuthError):
        async with client:
            pass
