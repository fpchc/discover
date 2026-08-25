"""插件系统：导入各内置插件，显式登记启动顺序。

启动顺序 = 下方 PLUGIN_REGISTRY 显式登记顺序（dict 保持插入序）。
logging 必须最先，保证统一日志在后续插件启动前配置好。
新增内置插件：加 import + 在显式登记处按序追加。
"""

from app.plugins.base import PLUGIN_REGISTRY, Plugin, PluginManager, register
from app.plugins.db_plugin import DBPlugin
from app.plugins.llm_plugin import LLMPlugin
from app.plugins.logging_plugin import LoggingPlugin
from app.plugins.mcp_plugin import MCPPlugin
from app.plugins.redis_plugin import RedisPlugin
from app.plugins.storage_plugin import StoragePlugin

# 显式登记（@register 仅做重名校验与成员登记；此处覆盖为权威顺序）。
PLUGIN_REGISTRY.clear()
PLUGIN_REGISTRY["logging"] = LoggingPlugin
PLUGIN_REGISTRY["db"] = DBPlugin
PLUGIN_REGISTRY["storage"] = StoragePlugin
PLUGIN_REGISTRY["redis"] = RedisPlugin
PLUGIN_REGISTRY["mcp"] = MCPPlugin
PLUGIN_REGISTRY["llm"] = LLMPlugin

__all__ = [
    "PLUGIN_REGISTRY",
    "DBPlugin",
    "LLMPlugin",
    "LoggingPlugin",
    "MCPPlugin",
    "Plugin",
    "PluginManager",
    "RedisPlugin",
    "StoragePlugin",
    "register",
]
