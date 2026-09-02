"""MCP 能力：Streamable HTTP 客户端 + 连接/引用计数管理器。"""

from app.capabilities.mcp.client import MCPCallResult, MCPClient, MCPToolInfo
from app.capabilities.mcp.manager import MCPManager

__all__ = [
    "MCPCallResult",
    "MCPClient",
    "MCPManager",
    "MCPToolInfo",
]
