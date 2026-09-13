"""组合根（bootstrap）：进程装配——应用工厂 + 服务容器构造 + 扩展加载。

本层只做依赖组装，不承载业务逻辑；实现分布在 interfaces / application /
domain / infrastructure 四层。服务容器类型本身定义在 application（避免
interfaces 反向依赖组合根）。
"""

from app.application.services import AppServices
from app.bootstrap.application import create_app

__all__ = [
    "AppServices",
    "create_app",
]
