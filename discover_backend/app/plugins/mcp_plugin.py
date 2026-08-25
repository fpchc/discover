"""mcp 插件：加载 MCP 服务注册表 + MCPManager（客户端引用计数管理）。

自原 container 迁出：load_mcp_servers 异步读 yaml（anyio 线程池），
MCPManager 持有注册表负责 acquire / release / close。
"""

from __future__ import annotations

from app.config.loader import MCPRegistry, load_mcp_servers
from app.config.settings import Settings
from app.plugins.base import Plugin, register
from app.tools.mcp_manager import MCPManager


@register
class MCPPlugin(Plugin):
    """MCP 服务注册表 + 客户端管理器。"""

    name = "mcp"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._registry: MCPRegistry | None = None
        self._manager: MCPManager | None = None

    @classmethod
    def is_enabled(cls, settings: Settings) -> bool:
        return settings.mcp_enabled

    @property
    def registry(self) -> MCPRegistry:
        assert self._registry is not None
        return self._registry

    @property
    def manager(self) -> MCPManager:
        assert self._manager is not None
        return self._manager

    async def startup(self) -> None:
        self._registry = await load_mcp_servers(self._settings.mcp_registry_path)
        self._manager = MCPManager(self._settings, self._registry)

    async def shutdown(self) -> None:
        if self._manager is not None:
            await self._manager.close_all()
