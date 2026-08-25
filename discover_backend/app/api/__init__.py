"""接入层路由（controller）：api/ 只暴露路由信息，不承载其他职责。"""

from app.api.routes_artifacts import router as artifacts_router
from app.api.routes_chat import router as chat_router

__all__ = ["artifacts_router", "chat_router"]
