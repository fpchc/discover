"""统一登录（elecnest SSO）HTTP 接入层测试——进程内 ASGI，无 DB / 无环境变量。

对话边界约束（CLAUDE.md §9）：不连数据库、不读 `.env` / `os.environ`。
构建最小 app 只挂 auth 路由 + 全局异常中间件，用依赖覆盖注入 stub 服务边界，
覆盖：路由注册 / 请求体校验（422）/ 成功响应形状 / 错误状态映射（400、401）。
外部 HTTP 与数据库都不触达（CLAUDE.md §12）。
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from app.api.auth import router as auth_router
from app.config.settings import Settings
from app.container import get_services
from app.errors.base import BadRequestError, UnauthorizedError
from app.middleware.exceptions import ExceptionHandlingMiddleware
from app.schemas.auth import LoginResponse
from fastapi import FastAPI


class _StubAuth:
    """桩服务：记录调用参数，可注入成功结果或领域异常（服务边界 mock）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.result: LoginResponse | None = None
        self.error: BaseException | None = None

    async def login_with_elecnest(self, token: str, uid: int) -> LoginResponse:
        self.calls.append((token, uid))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _make_app(stub: _StubAuth) -> FastAPI:
    """最小 app：仅 auth 路由 + 异常中间件；get_services 依赖覆盖注入 stub。"""
    settings = Settings(
        _env_file=None, jwt_secret_key="test-secret-0123456789abcdef0123456789abcdef"
    )
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.add_middleware(ExceptionHandlingMiddleware, settings=settings)
    services = SimpleNamespace(auth=stub)
    app.dependency_overrides[get_services] = lambda: services
    return app


async def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000/")


async def test_elecnest_login_success_returns_token() -> None:
    stub = _StubAuth()
    stub.result = LoginResponse(account_id="acct-1", token="jwt-1", name="张三")
    async with await _client(_make_app(stub)) as client:
        response = await client.post(
            "/api/v1/auth/login/elecnest",
            json={"token": "998a6944814f8efb4d0c2a35c6d2e8369e1065ded6cdfaf62364983c64abcfbe", "uid": "329806"},
        )
    assert response.status_code == 200
    body = LoginResponse.model_validate(response.json())
    assert body.account_id == "acct-1"
    assert body.token == "jwt-1"
    assert body.name == "张三"
    # 路由把 body 字段原样透传给服务
    assert stub.calls == [("sso-token", 88001)]


async def test_elecnest_login_disabled_maps_to_400() -> None:
    stub = _StubAuth()
    stub.error = BadRequestError("统一登录未启用")
    async with await _client(_make_app(stub)) as client:
        response = await client.post(
            "/api/v1/auth/login/elecnest",
            json={"token": "sso-token", "uid": 88002},
        )
    assert response.status_code == 400


async def test_elecnest_login_invalid_credentials_maps_to_401() -> None:
    stub = _StubAuth()
    stub.error = UnauthorizedError("统一登录校验失败")
    async with await _client(_make_app(stub)) as client:
        response = await client.post(
            "/api/v1/auth/login/elecnest",
            json={"token": "bad-token", "uid": 88003},
        )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "sso-token"},  # 缺 uid
        {"uid": 88004},  # 缺 token
        {"token": "", "uid": 88005},  # token 为空
    ],
)
async def test_elecnest_login_invalid_body_maps_to_422(payload: dict[str, object]) -> None:
    stub = _StubAuth()
    async with await _client(_make_app(stub)) as client:
        response = await client.post("/api/v1/auth/login/elecnest", json=payload)
    assert response.status_code == 422
    # 参数校验失败不触达服务
    assert stub.calls == []
