"""工具层（L2 代理 + L1 执行器）：三级目录、分发、MCP 客户端、脚本容器。"""

from platform_engine.tools.broker import (
    ToolActivation,
    ToolBroker,
    ToolCallRequest,
    ToolHit,
    ToolResult,
)
from platform_engine.tools.descriptor import (
    ToolDescriptor,
    ToolSource,
    mcp_qualified_name,
    script_qualified_name,
    split_qualified_name,
    to_chat_tool_spec,
)
from platform_engine.tools.mcp_client import MCPCallResult, MCPClient, MCPToolInfo
from platform_engine.tools.mcp_manager import MCPManager
from platform_engine.tools.script_executor import (
    ENV_SKILL_ROOT_DIR,
    ENV_WORKSPACE_DIR,
    ScriptExecution,
    ScriptExecutor,
)

__all__ = [
    "ENV_SKILL_ROOT_DIR",
    "ENV_WORKSPACE_DIR",
    "MCPCallResult",
    "MCPClient",
    "MCPManager",
    "MCPToolInfo",
    "ScriptExecution",
    "ScriptExecutor",
    "ToolActivation",
    "ToolBroker",
    "ToolCallRequest",
    "ToolDescriptor",
    "ToolHit",
    "ToolResult",
    "ToolSource",
    "mcp_qualified_name",
    "script_qualified_name",
    "split_qualified_name",
    "to_chat_tool_spec",
]
