"""账号认证数据模型（跨边界 DTO，CLAUDE.md §3）。

账号 ID 在领域层一律用 str(uuid.UUID) 虚线形式（36 字符）；持久化 ORM 见
app/db/models.py 的 Account（id 为原生 uuid 类型）。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.conversations import DailyUsageItem


class AccountStatus(StrEnum):
    """账号生命周期状态（DDL 默认 active）。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class UserType(StrEnum):
    """账号登录来源（accounts.user_type，DDL 默认 password）。"""

    PASSWORD = "password"
    ELECNEST = "elecnest"


class LoginRequest(BaseModel):
    """登录请求体（手机号 + 密码）。"""

    phone: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class ElecnestLoginRequest(BaseModel):
    """统一登录请求体（公司统一登录 token + uid）。"""

    token: str = Field(min_length=1, max_length=2048)
    uid: int


class ElecnestUserInfo(BaseModel):
    """统一登录返回的用户资料（对外契约字段，见 `getUserInfoByToken` 的 DTO）。

    与公司接口字段一一对应（`dcWxOpenid` / `dcWxNickName` 驼峰别名映射）。
    字段允许空值/缺失（Java POJO 同样容忍 null），由调用方做回退处理。
    """

    uid: int
    username: str | None = None
    nickname: str | None = None
    phone: str | None = None
    avatar: str | None = None
    email: str | None = None
    dc_wx_openid: str | None = Field(default=None, alias="dcWxOpenid")
    dc_wx_nickname: str | None = Field(default=None, alias="dcWxNickName")


class ElecnestUserInfoResponse(BaseModel):
    """统一登录接口外层响应（`{data: {...} | null}`）。"""

    data: ElecnestUserInfo | None = None


class LoginResponse(BaseModel):
    """登录 / 刷新响应：account_id + 访问令牌 + 刷新令牌 + 显示名。

    token 为短期访问令牌（Bearer 认证）；refresh_token 为长期刷新令牌（仅
    /auth/refresh 用，Redis 权威）；expires_in 为访问令牌剩余秒数（前端预刷新）。
    """

    account_id: str
    token: str
    refresh_token: str
    expires_in: int
    name: str | None = None


class RefreshTokenRequest(BaseModel):
    """刷新令牌续期请求体（POST /auth/refresh；轮换制，旧刷新令牌作废）。"""

    refresh_token: str = Field(min_length=1, max_length=2048)


class LogoutRequest(BaseModel):
    """登出请求体：当前会话的刷新令牌（与 Bearer 访问令牌一并作废，DEL 幂等）。"""

    refresh_token: str = Field(min_length=1, max_length=2048)


class AccountRecord(BaseModel):
    """账号记录（读取接口返回；password_hash 永不外泄）。"""

    account_id: str
    name: str
    phone: str
    avatar: str | None = None
    status: AccountStatus = AccountStatus.ACTIVE
    is_system: bool = False
    user_type: UserType = UserType.PASSWORD
    created_at: datetime
    last_login_at: datetime | None = None


class UpdateAccountRequest(BaseModel):
    """更新当前账号资料（PATCH /users/me；当前仅支持昵称）。"""

    name: str | None = Field(default=None, min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    """修改当前账号密码（POST /users/me/password；必须携带原密码校验）。"""

    old_password: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=1, max_length=255)


class AvatarConfig(BaseModel):
    """头像上传限制（GET /users/me/avatar-config；供前端本地校验输入）。

    与 /files/upload 的通用上传限制解耦——头像显示目标小（≤96px 圆形），
    约束更严（仅图片、体积小、边长区间）。阈值全部来自配置，前端不硬编码。
    """

    max_size_bytes: int
    allowed_extensions: list[str]
    max_dimension: int
    min_dimension: int


class UserUsage(BaseModel):
    """账号 token 用量（聚合 messages.created_by 的回合用量）。

    平铺字段便于前端直接消费；conversation_count 为去重后的会话数。
    """

    account_id: str
    name: str
    conversation_count: int = 0
    message_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_read_tokens: int = 0
    cached_write_tokens: int = 0


class DailyUsage(BaseModel):
    """账号近 days 天每日 token 用量（趋势图数据源；items 零填充、升序、每天一条）。

    口径与 UserUsage 完全一致，仅按 created_at 自然日（GMT+8）分组；无数据日为 0。
    """

    account_id: str
    name: str
    days: int
    items: list[DailyUsageItem] = Field(default_factory=list)
