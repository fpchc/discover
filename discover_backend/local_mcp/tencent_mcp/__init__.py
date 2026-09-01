"""腾讯联网搜索 MCP 服务包：对外只暴露显式入口。"""

from local_mcp.tencent_mcp.main import SERVER_NAME, SERVER_VERSION, create_app
from local_mcp.tencent_mcp.providers import (
    SearchProvider,
    SearchServiceError,
    TencentSearchProvider,
)
from local_mcp.tencent_mcp.settings import TencentMCPSettings

__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "SearchProvider",
    "SearchServiceError",
    "TencentMCPSettings",
    "TencentSearchProvider",
    "create_app",
]
