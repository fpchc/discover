"""账号认证接口（L4，controller）：登录 + 当前用户 + 用量。

路由只做参数提取与转调（SRP）；认证逻辑在 AuthService，校验在 deps。
`GET /users` 为超级用户专属（is_system=true），用于区分各账号 token 使用量。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_account, get_current_account_id, require_superuser
from app.container import AppServices, get_services
from app.errors.base import UnauthorizedError
from app.schemas.auth import AccountRecord, LoginRequest, LoginResponse, UserUsage

router = APIRouter(tags=["auth"])


@router.post("/auth/login")
async def login(
    body: LoginRequest,
    services: AppServices = Depends(get_services),
) -> LoginResponse:
    """手机号 + 密码登录：校验 Argon2id 哈希 → 签发 JWT。"""
    assert services.auth is not None
    return await services.auth.login(body.phone, body.password)


@router.get("/users/me")
async def current_account(account: AccountRecord = Depends(get_current_account)) -> AccountRecord:
    """当前登录账号信息。"""
    return account


@router.get("/users/me/usage")
async def current_usage(
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> UserUsage:
    """当前账号 token 用量（按 created_by 聚合 messages）。"""
    assert services.auth is not None
    usage = await services.auth.get_user_usage(account_id)
    if usage is None:
        raise UnauthorizedError("账号不存在")
    return usage


@router.get("/users")
async def list_users(
    superuser: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> list[UserUsage]:
    """全量账号 token 用量（仅超级用户；区分各账号使用量）。"""
    del superuser  # 依赖仅用于鉴权
    assert services.auth is not None
    return await services.auth.list_users_with_usage()
