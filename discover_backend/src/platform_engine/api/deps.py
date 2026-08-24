"""接入层共享服务容器：应用生命周期内单例 + FastAPI 依赖。

启动时加载 LLM/MCP 注册表并刷新智能体索引；关闭时释放会话运行时
（MCP 引用计数）与 LLM 连接。热重载开关开启时启动后台轮询任务。
"""

import asyncio

import anyio
from fastapi import Request

from platform_engine.config.loader import LLMProvider, load_llm_providers, load_mcp_servers
from platform_engine.config.settings import Settings
from platform_engine.db.engine import Database
from platform_engine.llm.client import LLMClient
from platform_engine.llm.providers import ProviderRegistry, resolve_api_key
from platform_engine.registry.hot_reload import HotReloader
from platform_engine.registry.registry import AgentRegistry
from platform_engine.runtime.runner import Runtime
from platform_engine.session.service import SessionService
from platform_engine.storage.base import BaseStorage
from platform_engine.storage.local import LocalStorage
from platform_engine.tools.mcp_manager import MCPManager
from platform_engine.tools.script_executor import ScriptExecutor


class AppServices:
    """平台服务容器。由 create_app 构造，经 lifespan 启动 / 关闭。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = LLMClient(settings)
        self.providers: ProviderRegistry | None = None
        self.mcp_manager: MCPManager | None = None
        self.script_executor: ScriptExecutor | None = None
        self.db: Database | None = None
        self.storage: BaseStorage | None = None
        self.sessions: SessionService | None = None
        self.registry: AgentRegistry | None = None
        self.runtimes: dict[str, Runtime] = {}
        self._reloader_scope: anyio.CancelScope | None = None
        self._reloader_task: asyncio.Task[None] | None = None

    async def startup(self) -> None:
        """加载注册表、刷新索引、启动热重载后台任务。"""
        await self.llm.__aenter__()
        providers_registry = await load_llm_providers(self.settings.llm_providers_path)
        mcp_registry = await load_mcp_servers(self.settings.mcp_registry_path)
        self.providers = ProviderRegistry(providers_registry)
        self.mcp_manager = MCPManager(self.settings, mcp_registry)
        self.script_executor = ScriptExecutor(self.settings)
        self.db = Database(self.settings)
        self.storage = LocalStorage(self.settings.storage_root_dir)
        self.sessions = SessionService(self.settings, self.db, self.storage)
        self.registry = AgentRegistry(self.settings, mcp_registry)
        await self.registry.refresh()
        reloader = HotReloader(self.registry, self.settings)
        scope = anyio.CancelScope()
        self._reloader_scope = scope
        # pragma: 简化 — 单常驻协程在 anyio v4 无顶层 create_task；任务组宿主模式
        # 跨任务退出会触发 cancel-scope 跨任务报错，宿主任务内嵌任务组取消时又会
        # 死锁（同 protocol/emitter.py 注释），故用 asyncio.create_task + 显式
        # 取消/join 管理生命周期（CLAUDE.md §4 禁令针对「裸建任务不管理生命周期」）。
        self._reloader_task = asyncio.create_task(self._run_reloader(reloader, scope))

    async def shutdown(self) -> None:
        """释放会话运行时 MCP 引用、停止热重载、关闭 LLM 连接。"""
        for runtime in self.runtimes.values():
            await runtime.close()
        self.runtimes.clear()
        if self._reloader_task is not None and self._reloader_scope is not None:
            self._reloader_scope.cancel()
            await self._reloader_task
            self._reloader_task = None
            self._reloader_scope = None
        if self.db is not None:
            await self.db.dispose()
        await self.llm.__aexit__(None, None, None)

    async def _run_reloader(self, reloader: HotReloader, scope: anyio.CancelScope) -> None:
        """常驻协程宿主：取消作用域进入/退出在同一任务，由 shutdown 跨任务取消。"""
        with scope:
            await reloader.run()

    def _resolve_api_key(self, provider: LLMProvider) -> str:
        """绑定 settings 的密钥解析：真实环境变量优先，其次 .env 文件。"""
        return resolve_api_key(provider, settings=self.settings)

    def get_runtime(self, session_id: str) -> Runtime:
        """获取（或创建）会话级运行时。创建后复用同一工具代理。"""
        runtime = self.runtimes.get(session_id)
        if runtime is None:
            assert self.providers is not None
            assert self.mcp_manager is not None
            assert self.script_executor is not None
            assert self.sessions is not None
            assert self.registry is not None
            assert self.db is not None
            runtime = Runtime(
                settings=self.settings,
                sessions=self.sessions,
                registry=self.registry,
                llm=self.llm,
                providers=self.providers,
                resolve_api_key=self._resolve_api_key,
                mcp_manager=self.mcp_manager,
                script_executor=self.script_executor,
                db=self.db,
            )
            self.runtimes[session_id] = runtime
        return runtime

    async def drop_runtime(self, session_id: str) -> None:
        """会话删除时释放其运行时（MCP 引用计数）。"""
        runtime = self.runtimes.pop(session_id, None)
        if runtime is not None:
            await runtime.close()


def get_services(request: Request) -> AppServices:
    """FastAPI 依赖：取应用级服务容器。"""
    services = request.app.state.services
    assert isinstance(services, AppServices)
    return services
