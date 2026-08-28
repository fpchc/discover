"""FastAPI 认证依赖：从 `Authorization: Bearer <JWT>` 解析当前账号。

三层依赖：
- get_current_account_id：仅解 JWT 得 account_id（不查库，供隔离过滤用）；
- get_current_account：查库取完整账号（供 /users/me 等，账号被删即 401）；
- require_superuser：is_system=true 才放行（管理接口），否则 403。
"""

from __future__ import annotations

from fastapi import Depends, Request

from app.container import AppServices, get_services
from app.errors.base import ForbiddenError, UnauthorizedError
from app.schemas.auth import AccountRecord


def _bearer_token(request: Request) -> str:
    """提取 Authorization: Bearer <token>；缺失/畸形 → 401。"""
    header = request.headers.get("Authorization")
    if not header:
        raise UnauthorizedError("未登录")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError("未登录")
    return token.strip()


def get_current_account_id(
    request: Request,
    services: AppServices = Depends(get_services),
) -> str:
    """解析 JWT 返回 account_id（无效/过期 → 401；不查库）。"""
    assert services.auth is not None
    return services.auth.decode_token(_bearer_token(request))


async def get_current_account(
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> AccountRecord:
    """当前账号完整记录（查库；账号不存在 → 401）。"""
    assert services.auth is not None
    account = await services.auth.get_account(account_id)
    if account is None:
        raise UnauthorizedError("账号不存在")
    return account


async def require_superuser(
    account: AccountRecord = Depends(get_current_account),
) -> AccountRecord:
    """仅超级用户（is_system=true）可访问；其余 403。"""
    if not account.is_system:
        raise ForbiddenError("需要超级用户权限")
    return account
