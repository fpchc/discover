"""账号认证接口（L4，controller）：登录 + 当前用户 + 用量。

路由只做参数提取与转调（SRP）；认证逻辑在 AuthService，校验在 deps。
`GET /users` 为超级用户专属（is_system=true），用于区分各账号 token 使用量。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, UploadFile

from app.bootstrap.container import AppServices, get_services
from app.interfaces.http.deps import (
    get_bearer_token,
    get_current_account,
    get_current_account_id,
    require_superuser,
)
from app.interfaces.schemas.auth import (
    AccountRecord,
    AvatarConfig,
    ChangePasswordRequest,
    DailyUsage,
    ElecnestLoginRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshTokenRequest,
    UpdateAccountRequest,
    UserUsage,
)
from app.shared.errors.base import BadRequestError, UnauthorizedError

router = APIRouter(tags=["auth"])


@router.post("/auth/login")
async def login(
    body: LoginRequest,
    services: AppServices = Depends(get_services),
) -> LoginResponse:
    """手机号 + 密码登录：校验 Argon2id 哈希 → 签发 JWT。"""
    assert services.auth is not None
    return await services.auth.login(body.phone, body.password)


@router.post("/auth/login/elecnest")
async def elecnest_login(
    body: ElecnestLoginRequest,
    services: AppServices = Depends(get_services),
) -> LoginResponse:
    """公司统一登录：token + uid → 统一登录用户信息 → 本地注册/复用 → 签发令牌对。"""
    assert services.auth is not None
    return await services.auth.login_with_elecnest(body.token, body.uid)


@router.post("/auth/refresh")
async def refresh_token(
    body: RefreshTokenRequest,
    services: AppServices = Depends(get_services),
) -> LoginResponse:
    """刷新令牌换新令牌对（轮换制：旧刷新令牌作废，防重用；Redis 权威）。"""
    assert services.auth is not None
    return await services.auth.refresh(body.refresh_token)


@router.post("/auth/logout", status_code=204)
async def logout(
    body: LogoutRequest,
    access_token: str = Depends(get_bearer_token),
    services: AppServices = Depends(get_services),
) -> None:
    """服务端登出：作废当前访问令牌 + 刷新令牌（DEL 幂等，无 key 也返回 204）。"""
    assert services.auth is not None
    await services.auth.logout(access_token, body.refresh_token)


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


@router.get("/users/me/usage/daily")
async def current_daily_usage(
    # pragma: 简化 — 天数上下界为 API 契约固定值（需求明确默认 30 / 上限 90），不进配置
    days: int = Query(default=30, ge=1, le=90),
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> DailyUsage:
    """当前账号近 days 天每日 token 用量（趋势图数据源；零填充、升序）。"""
    assert services.auth is not None
    usage = await services.auth.get_user_daily_usage(account_id, days=days)
    if usage is None:
        raise UnauthorizedError("账号不存在")
    return usage


@router.get("/users/me/avatar-config")
async def avatar_config(services: AppServices = Depends(get_services)) -> AvatarConfig:
    """头像上传限制配置（供前端本地校验输入；阈值全部配置驱动）。"""
    assert services.auth is not None
    return await services.auth.avatar_config()


@router.patch("/users/me")
async def update_account(
    body: UpdateAccountRequest,
    account: AccountRecord = Depends(get_current_account),
    services: AppServices = Depends(get_services),
) -> AccountRecord:
    """更新当前账号资料（当前支持昵称；白名单字段防越权）。"""
    assert services.auth is not None
    return await services.auth.update_account(account.account_id, name=body.name)


@router.post("/users/me/avatar")
async def upload_avatar(
    file: UploadFile,
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> AccountRecord:
    """更换头像：图片格式 / 体积 / magic bytes 校验（约束严于通用上传）。"""
    assert services.auth is not None
    limit = services.settings.avatar_max_size_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise BadRequestError(f"头像超过大小上限（{limit} 字节）")
    return await services.auth.change_avatar(
        account_id,
        filename=file.filename or "avatar.png",
        content=content,
        mimetype=file.content_type or "",
    )


@router.post("/users/me/password")
async def change_password(
    body: ChangePasswordRequest,
    account: AccountRecord = Depends(get_current_account),
    services: AppServices = Depends(get_services),
) -> AccountRecord:
    """修改当前账号密码：必须填写原密码校验通过才允许修改。"""
    assert services.auth is not None
    return await services.auth.change_password(
        account.account_id,
        old_password=body.old_password,
        new_password=body.new_password,
    )


@router.get("/users")
async def list_users(
    superuser: AccountRecord = Depends(require_superuser),
    services: AppServices = Depends(get_services),
) -> list[UserUsage]:
    """全量账号 token 用量（仅超级用户；区分各账号使用量）。"""
    del superuser  # 依赖仅用于鉴权
    assert services.auth is not None
    return await services.auth.list_users_with_usage()
