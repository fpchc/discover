"""MCP 扩展：加载 MCP 服务注册表 + MCPManager（客户端引用计数管理）。

startup 异步加载 yaml（anyio 线程池）并构造 MCPManager；shutdown 关闭全部
残留连接。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config.loader import MCPRegistry, load_mcp_servers
from app.extensions.base import active_settings
from app.tools.mcp_manager import MCPManager

_manager: MCPManager | None = None
_registry: MCPRegistry | None = None


def is_enabled() -> bool:
    """由配置开关控制。"""
    return active_settings().mcp_enabled


def init_app(app: FastAPI | None) -> None:
    """注册表与管理器惰性构造，startup 加载。"""


async def startup(app: FastAPI) -> None:
    """加载 MCP 服务注册表并构造管理器。"""
    global _manager, _registry
    _registry = await load_mcp_servers(active_settings().mcp_registry_path)
    _manager = MCPManager(active_settings(), _registry)


async def shutdown(app: FastAPI) -> None:
    """关闭全部残留客户端连接。"""
    global _manager
    if _manager is not None:
        await _manager.close_all()
        _manager = None


def get_manager() -> MCPManager:
    """取 MCP 管理器；扩展未启用时抛断言。"""
    assert _manager is not None
    return _manager


def get_registry() -> MCPRegistry:
    """取 MCP 服务注册表。"""
    assert _registry is not None
    return _registry
