"""公司统一登录（elecnest SSO）客户端。

职责单一（SRP，CLAUDE.md §6）：token + uid → 统一登录用户资料。对外 HTTP 走
注入的 httpx.AsyncClient（唯一出口，CLAUDE.md §1）；仅解析与规范化，不含注册逻辑。
`getUserInfoByToken` 语义对齐：昵称缺失回退用户名；校验失败 / 接口异常一律
返回 None，由 AuthService 统一转 401（防账号枚举，与手机号登录口径一致）。
"""

from __future__ import annotations

import logging

import httpx

from app.config.settings import Settings
from app.schemas.auth import ElecnestUserInfo, ElecnestUserInfoResponse

logger = logging.getLogger(__name__)


class ElecnestSSOClient:
    """统一登录用户信息客户端（注入 httpx.AsyncClient，生命周期由容器管理）。"""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    async def get_user_info(self, token: str, uid: int) -> ElecnestUserInfo | None:
        """按 token + uid 换取统一登录用户资料；data 缺失 / 接口异常返回 None。"""
        try:
            response = await self._http.get(
                self._settings.elecnest_get_user_info_url,
                params={"token": token, "uid": uid},
            )
            response.raise_for_status()
            payload = ElecnestUserInfoResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("统一登录获取用户信息失败（uid=%s）：%s", uid, exc)
            return None
        data = payload.data
        if data is None:
            return None
        if not data.nickname:
            data.nickname = data.username
        return data
