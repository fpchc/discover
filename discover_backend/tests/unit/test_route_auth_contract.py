"""路由登录声明防腐层测试（无 DB）：声明、结构与 HTTP 行为三层锁定。

结构与声明：
1. 每条 /api/v1 路由恰好一个守卫标记（新增路由不标 → 失败）；
2. `verify_route_guards` 通过（标记与依赖一致，兜住装饰器顺序写反）；
3. 守卫清单快照（方法 + 路径 → 守卫）与期望一致，鉴权变更必留 diff。

HTTP 行为（防腐：FastAPI 升级 / 路由类改动不得让拦截失效）：
4. 受保护路由匿名请求一律 401（遍历真实路由表，新增路由自动纳入）；
5. 鉴权先于参数校验（空 body 也是 401，不是 422）；
6. 公开路由不带守卫（无令牌仍可达）；
7. 一次请求只解析一次账号（路由级守卫与签名内 Depends 命中同一缓存键）。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from app.application.dto.auth import AccountRecord
from app.application.identity.service import AuthService
from app.application.services import AppServices
from app.config.settings import Settings
from app.interfaces.http import (
    assistants_router,
    auth_router,
    chat_router,
    conversations_router,
    files_router,
)
from app.interfaces.http.auth_guard import (
    LoginRoute,
    declared_guards,
    login_required,
    verify_route_guards,
)
from app.interfaces.http.deps import get_current_account
from app.interfaces.middleware import ExceptionHandlingMiddleware
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute

_API_PREFIX = "/api/v1"
_ROUTERS: tuple[APIRouter, ...] = (
    auth_router,
    chat_router,
    files_router,
    conversations_router,
    assistants_router,
)

# 方法 + 全路径 → 守卫；新增/调整鉴权必须同步登记（这就是排查入口）
_EXPECTED_GUARDS: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/auth/login"): "public",
    ("POST", "/api/v1/auth/login/elecnest"): "public",
    ("POST", "/api/v1/auth/refresh"): "public",
    ("POST", "/api/v1/auth/logout"): "bearer_required",
    ("GET", "/api/v1/users/me"): "login_required",
    ("GET", "/api/v1/users/me/usage"): "login_required",
    ("GET", "/api/v1/users/me/usage/daily"): "login_required",
    ("GET", "/api/v1/users/me/avatar-config"): "public",
    ("PATCH", "/api/v1/users/me"): "login_required",
    ("POST", "/api/v1/users/me/avatar"): "login_required",
    ("POST", "/api/v1/users/me/password"): "login_required",
    ("GET", "/api/v1/users"): "login_required",
    ("POST", "/api/v1/chat-messages"): "login_required",
    ("POST", "/api/v1/chat-messages/{conversation_id}/stop"): "login_required",
    ("GET", "/api/v1/conversations"): "login_required",
    ("GET", "/api/v1/conversations/{conversation_id}/messages"): "login_required",
    ("DELETE", "/api/v1/conversations/{conversation_id}"): "login_required",
    ("GET", "/api/v1/files/upload"): "public",
    ("POST", "/api/v1/files/upload"): "login_required",
    ("GET", "/api/v1/files/{file_id}/preview"): "public",
    ("GET", "/api/v1/assistants"): "public",
}


def test_api_routes_declare_expected_guards() -> None:
    """每条路由恰好一个标记，且守卫清单与快照一致。"""
    verify_route_guards(_ROUTERS)
    actual = {
        (method, f"{_API_PREFIX}{route.path}"): declared_guards(route)[0]
        for router in _ROUTERS
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods or []
    }
    assert actual == _EXPECTED_GUARDS


def test_route_without_marker_is_rejected() -> None:
    """新增路由漏标 → 装配期报错，不静默放行。"""
    router = APIRouter()

    @router.get("/unmarked")
    async def unmarked() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(RuntimeError, match="需且仅需一个标记"):
        verify_route_guards((router,))


def test_marker_above_router_decorator_is_rejected() -> None:
    """@login_required 写到 @router 上方 → 标记在，依赖没注入，同样报错。"""
    router = APIRouter(route_class=LoginRoute)

    @login_required
    @router.get("/late")
    async def late() -> dict[str, bool]:
        return {"ok": True}

    with pytest.raises(RuntimeError, match="与鉴权依赖不一致"):
        verify_route_guards((router,))


def test_public_route_with_auth_dependency_is_rejected() -> None:
    """@public 路由签名里误挂鉴权依赖 → 报错（避免公开路由被鉴权拦成 401）。"""
    router = APIRouter(route_class=LoginRoute)

    @router.get("/mixed")
    async def mixed(account_id: str = Depends(get_current_account)) -> dict[str, str]:
        return {"account_id": account_id}

    with pytest.raises(RuntimeError, match="需且仅需一个标记"):
        verify_route_guards((router,))


# ---- HTTP 行为（防腐层）：拦截必须真的发生在请求进入业务之前 ----

_PROBE_ACCOUNT = AccountRecord(
    account_id="00000000-0000-0000-0000-0000000000aa",
    name="契约探针",
    phone="13800000000",
    created_at=datetime(2026, 1, 1, tzinfo=UTC),
)


class _AuthProbe:
    """AuthService 替身：不碰 DB / Redis，返回预置账号并统计解析次数。"""

    def __init__(self, account: AccountRecord | None = None) -> None:
        self.account = account
        self.calls = 0

    async def resolve_current_account(self, token: str) -> AccountRecord | None:
        del token
        self.calls += 1
        return self.account


def _guarded_app(probe: _AuthProbe) -> FastAPI:
    """真实 routers + 真实守卫依赖 + 真实异常中间件；services.auth 换替身。"""
    settings = Settings(_env_file=None)
    app = FastAPI()
    services = AppServices(settings)
    services.auth = cast(AuthService, probe)
    app.state.services = services
    app.add_middleware(ExceptionHandlingMiddleware, settings=settings)
    for router in _ROUTERS:
        app.include_router(router, prefix=_API_PREFIX)
    return app


def _login_required_probes() -> list[tuple[str, str]]:
    """遍历真实路由表产出匿名探测请求：新增受保护路由自动纳入覆盖。"""
    probes: list[tuple[str, str]] = []
    for router in _ROUTERS:
        for route in router.routes:
            if not isinstance(route, APIRoute) or declared_guards(route) != ("login_required",):
                continue
            path = re.sub(r"\{[^}]+\}", "probe", f"{_API_PREFIX}{route.path}")
            probes.extend((method, path) for method in sorted(route.methods or []))
    return probes


@pytest.fixture()
async def probe_client() -> AsyncIterator[tuple[_AuthProbe, httpx.AsyncClient]]:
    """(auth 替身, HTTP 客户端)：足够跑通守卫，不触达 DB / Redis / 真实网络。"""
    probe = _AuthProbe()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_guarded_app(probe)), base_url="http://test"
    ) as client:
        yield probe, client


async def test_login_required_routes_reject_anonymous_requests(
    probe_client: tuple[_AuthProbe, httpx.AsyncClient],
) -> None:
    """每个声明的受保护路由都必须在 HTTP 边界 401（不止结构上标了标记）。"""
    _probe, client = probe_client
    probes = _login_required_probes()
    assert len(probes) == 13  # 与清单快照同源：少了说明遍历失效
    for method, path in probes:
        response = await client.request(method, path)
        assert response.status_code == 401, f"{method} {path} 未拦截匿名请求"
        assert response.json()["error"]["category"] == "auth"


async def test_guard_runs_before_body_validation(
    probe_client: tuple[_AuthProbe, httpx.AsyncClient],
) -> None:
    """鉴权先于参数校验：空 body 且无令牌 → 401（不是 422），避免泄漏接口细节。"""
    _probe, client = probe_client
    response = await client.post("/api/v1/chat-messages", json={})
    assert response.status_code == 401


async def test_bearer_required_route_rejects_anonymous(
    probe_client: tuple[_AuthProbe, httpx.AsyncClient],
) -> None:
    """@bearer_required：无 Bearer 头 → 401（不解析身份，但必须带头）。"""
    _probe, client = probe_client
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": "probe"})
    assert response.status_code == 401


async def test_public_route_is_not_blocked_by_guard(
    probe_client: tuple[_AuthProbe, httpx.AsyncClient],
) -> None:
    """@public：无令牌仍可达（防止守卫误注入把公开端点拦成 401）。"""
    _probe, client = probe_client
    response = await client.get("/api/v1/files/upload")
    assert response.status_code == 200


async def test_account_resolved_once_per_request(
    probe_client: tuple[_AuthProbe, httpx.AsyncClient],
) -> None:
    """路由级守卫与签名内 Depends 同键缓存：一次请求只解析一次账号（零重复验签）。"""
    probe, client = probe_client
    probe.account = _PROBE_ACCOUNT
    response = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer probe"})
    assert response.status_code == 200
    assert response.json()["account_id"] == _PROBE_ACCOUNT.account_id
    assert probe.calls == 1
