"""业务服务层（Facade）：对话历史 / 文件 / 工作区 / 认证等服务统一收拢。

对外只暴露显式入口（CLAUDE.md §13.1 隐藏实现细节）；跨边界 DTO 一律走
`app.schemas.*`，持久化仓库走 `app.repositories.*`。

分层目录（用户决策 2026-08）：services（业务逻辑）与 repositories（持久化）
集中管理，避免散落的 feature 包干扰观看。
"""

from app.services.auth import AuthService
from app.services.auth_security import JwtService, PasswordHasher
from app.services.conversations import ConversationService
from app.services.files import FileService, file_preview_path
from app.services.workspace import Workspace, WorkspaceManager

__all__ = [
    "AuthService",
    "ConversationService",
    "FileService",
    "JwtService",
    "PasswordHasher",
    "Workspace",
    "WorkspaceManager",
    "file_preview_path",
]
