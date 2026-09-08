"""FastAPI 认证依赖：从 `Authorization: Bearer <token>` 解析当前用户。

兼容模式（2026-09-07）：统一认证平台令牌为主；原本地登录（手机号+密码 /
elecnest SSO / 刷新 / 登出 / 改密码）恢复可用作为兼容回退。认证链：

- `_bearer_token`：提取 `Authorization: Bearer <token>`（缺失/畸形 → 401）；
- `get_current_account`：**本地验签**（HS256 + 共享密钥 + aud + iss +
  type=access，无网络）后经 `AuthService.resolve_current_account` 区分两种令牌：
  - 平台令牌（sub=平台 user_id，非本地账号 uuid）→ 按 auth_user_id
    find-or-create 本地账号（统一认证登录映射，自动建档）；
  - 原本地登录令牌（sub=本地账号 uuid）→ 按 accounts.id 直查 + 校验 Redis
    访问会话存在（登出/过期即 401，原登录语义）；
- `get_current_account_id`：取当前用户**本地账号 uuid 文本**——数据隔离与查询
  统一按本地账号 uuid（兼容模式下两套登录都不引入第二套用户标识）；
- `get_bearer_token`：仅提取原始 token（不校验；登出等幂等场景用）；
- `require_superuser`：is_system=true 才放行（管理接口；过渡期占位，权限码体系
  接入后替换），否则 403。
"""

from __future__ import annotations

from fastapi import Depends, Request

from app.bootstrap.container import AppServices, get_services
from app.interfaces.schemas.auth import AccountRecord
from app.shared.errors.base import ForbiddenError, UnauthorizedError


def _bearer_token(request: Request) -> str:
    """提取 Authorization: Bearer <token>；缺失/畸形 → 401。"""
    header = request.headers.get("Authorization")
    if not header:
        raise UnauthorizedError("未登录")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError("未登录")
    return token.strip()


def get_bearer_token(request: Request) -> str:
    """提取原始 token（不校验；登出等幂等场景用）。"""
    return _bearer_token(request)


async def get_current_account(
    request: Request,
    services: AppServices = Depends(get_services),
) -> AccountRecord:
    """当前用户本地账号：平台令牌 find-or-create / 原本地登录令牌直查 + Redis 会话。

    本地验签（HS256 + aud + iss + type=access）失败 → 401；解析不到账号 → 401。
    """
    assert services.auth is not None
    account = await services.auth.resolve_current_account(_bearer_token(request))
    if account is None:
        raise UnauthorizedError("账号不存在")
    return account


async def get_current_account_id(
    account: AccountRecord = Depends(get_current_account),
) -> str:
    """当前用户本地账号 uuid 文本：数据隔离与查询统一按此值（无第二标识）。"""
    return account.account_id


async def require_superuser(
    account: AccountRecord = Depends(get_current_account),
) -> AccountRecord:
    """仅超级用户（is_system=true）可访问；其余 403。

    过渡期占位：统一认证本地验签拿不到平台权限码，先用本地 is_system 标注
    （管理员经 provision --auth-user-id --superuser 绑定）；权限码体系接入后替换。
    """
    if not account.is_system:
        raise ForbiddenError("需要超级用户权限")
    return account
