"""MCP 客户端管理器（L1）：按服务标识复用连接、引用计数、懒启动。

认证令牌只存环境变量名，值经 Settings.resolve_secret 解析（真实环境变量优先，
其次 .env 文件，不写入 os.environ）。会话态服务器（per_session）由接入层按会话
独占管理；共享服务器跨会话复用。release 减引用后连接保留复用，close_idle 提供
空闲回收入口（当前由接入层按需触发，无后台定时任务）。
"""

import anyio

from platform_engine.config.loader import MCPRegistry, MCPServer
from platform_engine.config.settings import Settings
from platform_engine.errors.base import ConfigError
from platform_engine.tools.mcp_client import MCPClient


def _resolve_token(server: MCPServer, *, settings: Settings) -> str:
    """解析 MCP 认证令牌。未配置或缺失抛 ConfigError。"""
    env_name = server.auth.token_env
    if not env_name:
        return ""
    value = settings.resolve_secret(env_name)
    if not value:
        raise ConfigError(f"缺少 MCP 认证令牌环境变量：{env_name}")
    return value


class MCPManager:
    """MCP 客户端注册表：acquire 复用、release 减引用、close_idle 回收。"""

    def __init__(self, settings: Settings, registry: MCPRegistry) -> None:
        self._settings = settings
        self._registry = registry
        self._clients: dict[str, MCPClient] = {}
        self._refs: dict[str, int] = {}
        self._lock = anyio.Lock()

    def _find(self, server_id: str) -> MCPServer:
        for server in self._registry.servers:
            if server.id == server_id:
                return server
        raise ConfigError(f"未知 MCP 服务器：{server_id}")

    def concurrency_limit(self, server_id: str) -> int:
        """单服务并发上限（注册表服务专属值）。"""
        return self._find(server_id).concurrency_limit

    async def acquire(self, server_id: str) -> MCPClient:
        """获取客户端，引用计数 +1。首启时完成握手。"""
        server = self._find(server_id)
        async with self._lock:
            client = self._clients.get(server_id)
            if client is None:
                client = await self._start(server)
                self._clients[server_id] = client
            self._refs[server_id] = self._refs.get(server_id, 0) + 1
            return client

    def release(self, server_id: str) -> None:
        """引用计数 -1。计数归零后连接保留复用，等待空闲回收。"""
        refs = self._refs.get(server_id, 0)
        if refs > 1:
            self._refs[server_id] = refs - 1
        else:
            self._refs.pop(server_id, None)

    async def close_idle(self, server_id: str) -> None:
        """无引用时关闭连接并移除。仍有引用则不动作。"""
        if server_id in self._refs:
            return
        client = self._clients.pop(server_id, None)
        if client is not None:
            await client.__aexit__(None, None, None)

    async def _start(self, server: MCPServer) -> MCPClient:
        token = _resolve_token(server, settings=self._settings)
        client = MCPClient(server, self._settings, api_key=token)
        await client.__aenter__()
        return client
