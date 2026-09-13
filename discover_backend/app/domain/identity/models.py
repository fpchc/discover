"""身份域模型：账号状态/来源枚举与平台令牌载荷。

单一动机：承载「认证」的领域词汇，供领域服务（JwtService）与应用层共用。
HTTP 请求/响应壳（LoginRequest 等）留在 `app/application/dto/auth.py`。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AccountStatus(StrEnum):
    """账号生命周期状态（DDL 默认 active）。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class UserType(StrEnum):
    """账号来源（accounts.user_type，DDL 默认 password）。

    password=手机号+密码（兼容回退可用）；elecnest=原统一登录（兼容回退可用）；
    unified=统一认证平台登录映射建档（user_type 仅标记登录来源，不引入第二标识）。
    """

    PASSWORD = "password"
    ELECNEST = "elecnest"
    UNIFIED = "unified"


class PlatformTokenClaims(BaseModel):
    """统一认证平台 JWT 校验后的载荷（仅验签所需字段）。

    校验（签名/exp/aud/iss/type）由 JwtService.decode_platform_token 完成，
    此处只承载校验结果；user_id 即 JWT `sub`（平台用户标识，仅作登录映射键，
    不作为对外账号标识）。
    """

    user_id: str
    sid: str | None = None
    jti: str | None = None


class ElecnestUserInfo(BaseModel):
    """公司统一登录返回的用户资料（外部系统契约的领域投影）。"""

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
