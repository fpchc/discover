"""认证 HTTP 接入层测试（兼容模式）——进程内 ASGI，无 DB / 无环境变量。

对话边界约束（CLAUDE.md §9）：不连数据库、不读 `.env` / `os.environ`。
构建最小 app 只挂 auth 路由 + 全局异常中间件，用依赖覆盖注入 stub 服务边界。
覆盖：原本地登录端点（登录/elecnest/刷新/登出/改密码）恢复可用（兼容回退）；
公开端点无鉴权可访问；受保护端点无 Bearer → 401。错误体形状见异常中间件：
`{error: {category, message}}`。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
from app.bootstrap.container import get_services
from app.config.settings import Settings
from app.interfaces.http.auth import router as auth_router
from app.interfaces.middleware.exceptions import ExceptionHandlingMiddleware
from app.interfaces.schemas.auth import (
    AccountRecord,
    AvatarConfig,
    LoginResponse,
    UserType,
)
from app.shared.errors.base import UnauthorizedError
from fastapi import FastAPI

_ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


class _StubAuth:
    """桩服务：登录/刷新/登出/改密码走通（固定响应）；受保护端点校验固定账号。"""

    async def avatar_config(self) -> AvatarConfig:
        return AvatarConfig(
            max_size_bytes=2 * 1024 * 1024,
            allowed_extensions=["png", "jpg"],
            max_dimension=512,
            min_dimension=32,
        )

    async def login(self, phone: str, password: str) -> LoginResponse:
        del phone, password
        return LoginResponse(
            account_id=_ACCOUNT_ID,
            token="access-login",
            refresh_token="refresh-login",
            expires_in=3600,
            name="测试",
        )

    async def login_with_elecnest(self, token: str, uid: int) -> LoginResponse:
        del token, uid
        return LoginResponse(
            account_id=_ACCOUNT_ID,
            token="access-elecnest",
            refresh_token="refresh-elecnest",
            expires_in=3600,
        )

    async def refresh(self, refresh_token: str) -> LoginResponse:
        del refresh_token
        return LoginResponse(
            account_id=_ACCOUNT_ID,
            token="access-refresh",
            refresh_token="refresh-refresh",
            expires_in=3600,
        )

    async def logout(self, access_token: str, refresh_token: str) -> None:
        del access_token, refresh_token
        return None

    async def resolve_current_account(self, token: str) -> AccountRecord | None:
        del token
        return AccountRecord(
            account_id=_ACCOUNT_ID,
            name="测试",
            phone="13800138001",
            user_type=UserType.PASSWORD,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def change_password(
        self,
        account_id: str,
        *,
        old_password: str,
        new_password: str,
    ) -> AccountRecord:
        del old_password, new_password
        if account_id != _ACCOUNT_ID:
            raise UnauthorizedError("账号不存在")
        return AccountRecord(
            account_id=_ACCOUNT_ID,
            name="测试",
            phone="13800138001",
            user_type=UserType.PASSWORD,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def _make_app() -> FastAPI:
    """最小 app：仅 auth 路由 + 异常中间件；get_services 依赖覆盖注入 stub。"""
    settings = Settings(
        _env_file=None, jwt_secret_key="test-secret-0123456789abcdef0123456789abcdef"
    )
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.add_middleware(ExceptionHandlingMiddleware, settings=settings)
    app.dependency_overrides[get_services] = lambda: SimpleNamespace(
        auth=_StubAuth(), settings=settings
    )
    return app


async def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000/")


# ---- 原本地登录端点恢复可用（兼容回退） ----


async def test_login_endpoint_success() -> None:
    """POST /auth/login 恢复：手机号+密码 → LoginResponse。"""
    async with await _client(_make_app()) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"phone": "13800138001", "password": "pw-123"}
        )
    assert response.status_code == 200
    body = LoginResponse.model_validate(response.json())
    assert body.account_id == _ACCOUNT_ID
    assert body.token == "access-login"
    assert body.refresh_token == "refresh-login"


async def test_elecnest_login_endpoint_success() -> None:
    """POST /auth/login/elecnest 恢复：token + uid → LoginResponse。"""
    async with await _client(_make_app()) as client:
        response = await client.post(
            "/api/v1/auth/login/elecnest", json={"token": "sso-token", "uid": 88001}
        )
    assert response.status_code == 200
    body = LoginResponse.model_validate(response.json())
    assert body.account_id == _ACCOUNT_ID
    assert body.token == "access-elecnest"


async def test_refresh_endpoint_success() -> None:
    """POST /auth/refresh 恢复：刷新令牌 → 新令牌对。"""
    async with await _client(_make_app()) as client:
        response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "any"})
    assert response.status_code == 200
    body = LoginResponse.model_validate(response.json())
    assert body.token == "access-refresh"


async def test_logout_endpoint_returns_204() -> None:
    """POST /auth/logout 恢复：Bearer + 刷新令牌 → 204 空体。"""
    async with await _client(_make_app()) as client:
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "any"},
            headers={"Authorization": "Bearer access-login"},
        )
    assert response.status_code == 204
    assert response.content == b""


async def test_logout_requires_bearer() -> None:
    """登出无 Bearer → 401（get_bearer_token 提取阶段拦截）。"""
    async with await _client(_make_app()) as client:
        response = await client.post("/api/v1/auth/logout", json={"refresh_token": "any"})
    assert response.status_code == 401


async def test_change_password_endpoint_success() -> None:
    """POST /users/me/password 恢复：原密码校验通过 → AccountRecord。"""
    async with await _client(_make_app()) as client:
        response = await client.post(
            "/api/v1/users/me/password",
            json={"old_password": "old-pass", "new_password": "new-pass-123"},
            headers={"Authorization": "Bearer access-login"},
        )
    assert response.status_code == 200
    body = AccountRecord.model_validate(response.json())
    assert body.account_id == _ACCOUNT_ID


async def test_change_password_requires_bearer() -> None:
    """改密码无 Bearer → 401。"""
    async with await _client(_make_app()) as client:
        response = await client.post(
            "/api/v1/users/me/password",
            json={"old_password": "old-pass", "new_password": "new-pass-123"},
        )
    assert response.status_code == 401


# ---- 公开 / 受保护端点边界 ----


async def test_public_avatar_config_without_auth() -> None:
    """公开端点（头像上传限制）无需认证即可访问。"""
    async with await _client(_make_app()) as client:
        response = await client.get("/api/v1/users/me/avatar-config")
    assert response.status_code == 200
    config = AvatarConfig.model_validate(response.json())
    assert config.max_size_bytes > 0


async def test_protected_users_me_requires_bearer() -> None:
    """受保护端点无 Bearer → 401（未登录）。"""
    async with await _client(_make_app()) as client:
        response = await client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "未登录"
