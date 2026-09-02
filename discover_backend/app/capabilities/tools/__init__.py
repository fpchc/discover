"""工具能力：ToolBroker 三级目录与分发、描述符、脚本执行器、去重历史。

MCP 客户端 / 管理器见 app.capabilities.mcp。
"""

from app.capabilities.tools.broker import (
    ToolActivation,
    ToolBroker,
    ToolCallRequest,
    ToolHit,
    ToolResult,
)
from app.capabilities.tools.descriptor import (
    ToolDescriptor,
    ToolSource,
    mcp_qualified_name,
    script_qualified_name,
    split_qualified_name,
    to_chat_tool_spec,
)
from app.capabilities.tools.history import DedupStore
from app.capabilities.tools.script_executor import (
    ENV_SKILL_ROOT_DIR,
    ENV_WORKSPACE_DIR,
    ScriptExecution,
    ScriptExecutor,
)

__all__ = [
    "ENV_SKILL_ROOT_DIR",
    "ENV_WORKSPACE_DIR",
    "DedupStore",
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
