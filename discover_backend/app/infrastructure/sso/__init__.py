"""外部单点登录客户端（elecnest SSO，HTTP 走 httpx）。"""

from app.infrastructure.sso.elecnest import ElecnestSSOClient

__all__ = ["ElecnestSSOClient"]
