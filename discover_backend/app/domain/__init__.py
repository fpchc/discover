"""业务域：agent 注册 / 助手选择 / 会话 / 工作区 / 文件 / 认证。

对外只暴露显式入口（CLAUDE.md §13.1）；跨边界 DTO 走 interfaces.schemas，
持久化实现走 infrastructure。
"""

from app.domain.assistant.catalog import AssistantCatalog
from app.domain.auth.security import JwtService, PasswordHasher
from app.domain.auth.service import AuthService
from app.domain.conversation.service import ConversationService
from app.domain.file.service import FileService, file_preview_path
from app.domain.skill.registry import AgentRegistry
from app.domain.workspace.service import Workspace, WorkspaceManager

__all__ = [
    "AgentRegistry",
    "AssistantCatalog",
    "AuthService",
    "ConversationService",
    "FileService",
    "JwtService",
    "PasswordHasher",
    "Workspace",
    "WorkspaceManager",
    "file_preview_path",
]
