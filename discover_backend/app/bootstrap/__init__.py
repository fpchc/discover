"""组合根（bootstrap）：进程装配——应用工厂 + 服务容器 + 扩展加载。

本层只做依赖组装，不承载业务逻辑；实现全部在 interfaces/domain/runtime/
capabilities/infrastructure 各层。
"""

from app.bootstrap.application import create_app
from app.bootstrap.container import AppServices, get_services

__all__ = [
    "AppServices",
    "create_app",
    "get_services",
]
