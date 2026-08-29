"""ElecnestSSOClient 单元测试——纯逻辑，无 DB / 无真实网络。

外部 HTTP 用 httpx.MockTransport 拦截（CLAUDE.md §12：禁真实网络请求）；
Settings 以 _env_file=None 构造，不读取 .env / 环境变量（避免与全局约束冲突）。
"""

from __future__ import annotations

import httpx
from app.config.settings import Settings
from app.services.elecnest_sso import ElecnestSSOClient


def _client(handler: object) -> ElecnestSSOClient:
    """构造注入 MockTransport 的客户端（handler 为 httpx.MockTransport 回调）。"""
    settings = Settings(_env_file=None, elecnest_get_user_info_url="https://id.example.com/api")
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]  # 测试放宽：回调签名由 httpx 运行时保证
    http = httpx.AsyncClient(transport=transport)
    return ElecnestSSOClient(settings, http)


def _payload(data: object) -> httpx.Response:
    return httpx.Response(200, json={"data": data})


async def test_get_user_info_parses_nickname() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["token"] == "tok-1"
        assert request.url.params["uid"] == "88001"
        return _payload({"uid": 88001, "username": "zhang", "nickname": "张三"})

    info = await _client(_handler).get_user_info("tok-1", 88001)
    assert info is not None
    assert info.nickname == "张三"


async def test_get_user_info_falls_back_to_username() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return _payload({"uid": 88002, "username": "lisi", "nickname": ""})

    info = await _client(_handler).get_user_info("tok-2", 88002)
    assert info is not None
    assert info.nickname == "lisi"


async def test_get_user_info_null_data_returns_none() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return _payload(None)

    assert await _client(_handler).get_user_info("tok-3", 88003) is None


async def test_get_user_info_http_error_returns_none() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    assert await _client(_handler).get_user_info("tok-4", 88004) is None
