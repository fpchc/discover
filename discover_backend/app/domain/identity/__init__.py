"""身份域（domain/identity）：领域词汇 + 端口抽象（零框架、零 I/O）。

`models.py` 承载账号枚举、平台令牌载荷与 SSO 用户资料投影；`ports.py` 定义
会话存储契约。密码哈希 / JWT 实现在 `app/infrastructure/crypto/`，Redis 会话
存储在 `app/infrastructure/redis/`，SSO HTTP 客户端在 `app/infrastructure/sso/`；
认证用例编排在 `app/application/identity/`。
"""

from app.domain.identity.models import AccountStatus, PlatformTokenClaims, UserType
from app.domain.identity.ports import KeyValueStore, SessionStore

__all__ = [
    "AccountStatus",
    "KeyValueStore",
    "PlatformTokenClaims",
    "SessionStore",
    "UserType",
]
