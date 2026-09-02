"""接入层路由（controller）：api/ 只暴露路由信息，不承载其他职责。

所有路由一律收拢在本目录下；需要分层时在 api/ 内部建子目录。
"""

from app.interfaces.http.assistants import router as assistants_router
from app.interfaces.http.auth import router as auth_router
from app.interfaces.http.chat import router as chat_router
from app.interfaces.http.conversations import router as conversations_router
from app.interfaces.http.files import router as files_router

__all__ = [
    "assistants_router",
    "auth_router",
    "chat_router",
    "conversations_router",
    "files_router",
]
