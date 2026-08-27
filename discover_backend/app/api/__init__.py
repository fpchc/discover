"""接入层路由（controller）：api/ 只暴露路由信息，不承载其他职责。"""

from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.files import router as files_router

__all__ = ["chat_router", "conversations_router", "files_router"]
