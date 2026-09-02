"""东方财富（eastmoney）MCP 服务测试：提供方解析 + MCP 协议全链路互通 + 鉴权。

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
from local_mcp.eastmoney_mcp.main import create_app
from local_mcp.eastmoney_mcp.providers import EastmoneySearchProvider
from local_mcp.eastmoney_mcp.settings import EastmoneyMCPSettings

MCP_SERVER = MCPServer(
    id="eastmoney_mcp",
    transport="streamable_http",
    base_url="http://127.0.0.1:10002/mcp",
    auth=MCPServerAuth(token_env="EASTMONEY_MCP_TOKEN"),
    call_timeout_seconds=30,
    concurrency_limit=3,
)


def _settings(**overrides: object) -> EastmoneyMCPSettings:
    return EastmoneyMCPSettings(_env_file=None, **overrides)


def _eastmoney_articles_handler(captured: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url.params["param"])
        payload = {
            "code": 0,
            "msg": "OK",
            "result": {
                "cmsArticleWebOld": [
                    {
                        "title": "E1",
                        "content": "C1",
                        "date": "2026-08-01",
                        "mediaName": "南方财经网",
                        "url": "http://e/a",
                    }
                ]
            },
        }
        return httpx.Response(200, text=f"jQuery_news({json.dumps(payload, ensure_ascii=False)})")

    return httpx.MockTransport(handler)


# ---- 提供方：东方财富 ----
async def test_eastmoney_provider_jsonp_and_headers() -> None:
    captured: list[str] = []
    settings = _settings(eastmoney_min_interval_seconds=0.0)
    async with EastmoneySearchProvider(
        settings, http_client=httpx.AsyncClient(transport=_eastmoney_articles_handler(captured))
    ) as provider:
        text = await provider.search("腾讯云")
    assert json.loads(captured[0])["keyword"] == "腾讯云"
    assert "- E1" in text
    assert "南方财经网  ·  2026-08-01" in text
    assert "C1" in text


async def test_eastmoney_provider_empty_is_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="jQuery_news({})")

    settings = _settings(eastmoney_min_interval_seconds=0.0)
    async with EastmoneySearchProvider(
        settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ) as provider:
        text = await provider.search("不存在的东西")
    assert text == "未找到相关结果"


async def test_eastmoney_provider_dedupe_by_title() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "code": 0,
            "result": {
                "cmsArticleWebOld": [
                    {"title": "同题", "content": "A", "mediaName": "M1"},
                    {"title": "同题", "content": "B", "mediaName": "M2"},
                ]
            },
        }
        return httpx.Response(200, text=f"jQuery_news({json.dumps(payload, ensure_ascii=False)})")

    settings = _settings(eastmoney_min_interval_seconds=0.0)
    async with EastmoneySearchProvider(
        settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ) as provider:
        text = await provider.search("x")
    assert text.count("- 同题") == 1
    assert "B" not in text


# ---- MCP 协议全链路（平台真实客户端连本地服务）----
async def test_mcp_protocol_full_path_via_platform_client() -> None:
    settings = _settings(eastmoney_mcp_token="test-token", eastmoney_min_interval_seconds=0.0)
    east = EastmoneySearchProvider(
        settings,
        http_client=httpx.AsyncClient(transport=_eastmoney_articles_handler([])),
    )
    app = create_app(settings, providers={"web_search_eastmoney": east})
    client = MCPClient(
        MCP_SERVER,
        Settings(_env_file=None),
        api_key="test-token",
        http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    async with client:
        tools = await client.list_tools()
        assert [t.name for t in tools] == ["web_search_eastmoney"]
        result = await client.call_tool("web_search_eastmoney", {"query": "腾讯云"})
        assert result.is_error is False
        assert "- E1" in result.content


async def test_mcp_auth_rejected_wrong_token() -> None:
    app = create_app(_settings(eastmoney_mcp_token="right-token"))
    client = MCPClient(
        MCP_SERVER,
        Settings(_env_file=None),
        api_key="wrong-token",
        http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app)),
    )
    with pytest.raises(MCPAuthError):
        async with client:
            pass
