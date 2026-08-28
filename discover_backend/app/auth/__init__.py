"""账号认证功能包（Facade）。

对外只暴露显式入口（CLAUDE.md §13.1 隐藏实现细节）：AuthService 与 DTO。
注意：本包不得导入 deps——它依赖 app.container，而 container 又会
导入 auth.service 触发包初始化，会造成循环导入。认证依赖由接入层
直接按子模块导入（app.auth.deps）；路由统一放在 app/api/auth.py。
"""

from app.auth.models import (
    AccountRecord,
    AccountStatus,
    LoginRequest,
    LoginResponse,
    UserUsage,
)
from app.auth.service import AuthService

__all__ = [
    "AccountRecord",
    "AccountStatus",
    "AuthService",
    "LoginRequest",
    "LoginResponse",
    "UserUsage",
]
