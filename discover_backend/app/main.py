"""进程入口：uvicorn 启动（host/port 配置驱动）。

与 api 接入层解耦：main() 只负责把配置、应用工厂与 uvicorn 粘合起来，
属于进程级职责，不落入 api/ 包。
"""

import uvicorn

from app.application import create_app
from app.config.settings import get_settings

if __name__ == "__main__":
    """入口：uvicorn 启动（host/port 配置驱动）。"""
    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
