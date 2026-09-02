"""能力层（capabilities）：runtime 可调用的外部能力——LLM / 工具 / MCP。

各能力持有自己的实现与生命周期访问器；infrastructure 提供其底层技术实现。
"""

from app.capabilities.llm import LLMClient, ProviderRegistry
from app.capabilities.mcp import MCPClient, MCPManager
from app.capabilities.tools import ToolBroker

__all__ = [
    "LLMClient",
    "MCPClient",
    "MCPManager",
    "ProviderRegistry",
    "ToolBroker",
]
