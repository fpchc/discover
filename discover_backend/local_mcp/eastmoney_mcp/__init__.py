"""东方财富（eastmoney）MCP 服务包：对外只暴露显式入口。"""

from local_mcp.eastmoney_mcp.main import SERVER_NAME, SERVER_VERSION, create_app
from local_mcp.eastmoney_mcp.providers import (
    EastmoneySearchProvider,
    SearchProvider,
    SearchServiceError,
)
from local_mcp.eastmoney_mcp.settings import EastmoneyMCPSettings

__all__ = [
    "SERVER_NAME",
    "SERVER_VERSION",
    "EastmoneyMCPSettings",
    "EastmoneySearchProvider",
    "SearchProvider",
    "SearchServiceError",
    "create_app",
]
