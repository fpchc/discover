"""工具通道：端口词汇（描述符 / 限定名 / 调用与结果）+ ToolBroker + 脚本宿主。

工具是智能体操作环境的主要手段，因此与 MCP、工作区、存储同属 Environment。
"""

from app.environment.tools.broker import ToolBroker
from app.environment.tools.broker_contracts import ToolActivation, ToolHit
from app.environment.tools.models import (
    ToolCallRequest,
    ToolDescriptor,
    ToolResult,
    ToolSource,
    mcp_qualified_name,
    script_qualified_name,
    split_qualified_name,
    to_chat_tool_spec,
)
from app.environment.tools.script_executor import ScriptExecution, ScriptExecutor

__all__ = [
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
