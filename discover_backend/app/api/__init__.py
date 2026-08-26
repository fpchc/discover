"""接入层路由（controller）：api/ 只暴露路由信息，不承载其他职责。"""

from app.api.routes_chat import router as chat_router
from app.api.routes_files import router as files_router
from app.api.routes_history import router as history_router

__all__ = ["chat_router", "files_router", "history_router"]
