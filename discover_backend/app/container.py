"""接入层共享服务容器：应用生命周期内单例 + FastAPI 依赖。

扩展系统统一加载基础设施（logging/db/storage/redis/mcp/llm），startup 从
扩展访问器取类型化客户端并组装领域服务（conversation/registry/script_executor/
workspace/files/runtime）；shutdown 逆序关停扩展。热重载开关开启时启动后台
轮询任务。
"""

import asyncio
from collections.abc import Callable

import anyio
import httpx
from fastapi import FastAPI, Request

from app.catalog.assistant_catalog import AssistantCatalog
from app.config.loader import LLMProvider
from app.config.settings import Settings
from app.db.engine import Database
from app.extensions import shutdown_extensions, startup_extensions
from app.extensions.ext_database import get_database
from app.extensions.ext_llm import get_client, get_providers, resolve_api_key
from app.extensions.ext_mcp import get_manager, get_registry
from app.extensions.ext_storage import get_storage
from app.extensions.storage.base_storage import BaseStorage
from app.llm.client import LLMClient
from app.llm.providers import ProviderRegistry
from app.registry.hot_reload import HotReloader
from app.registry.registry import AgentRegistry
from app.runtime.runner import Runtime
from app.services.auth import AuthService
from app.services.conversations import ConversationService
from app.services.elecnest_sso import ElecnestSSOClient
from app.services.files import FileService
from app.services.workspace import WorkspaceManager
from app.tools.mcp_manager import MCPManager
from app.tools.script_executor import ScriptExecutor


class AppServices:
    """平台服务容器。由 create_app 构造，经 lifespan 启动 / 关闭。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm: LLMClient | None = None
        self.providers: ProviderRegistry | None = None
        self.mcp_manager: MCPManager | None = None
        self.script_executor: ScriptExecutor | None = None
        self.db: Database | None = None
        self.storage: BaseStorage | None = None
        self.workspaces: WorkspaceManager | None = None
        self.files: FileService | None = None
        self.catalog: AssistantCatalog | None = None
        self.conversation_service: ConversationService | None = None
        self.auth: AuthService | None = None
        self.registry: AgentRegistry | None = None
        self.elecnest: ElecnestSSOClient | None = None
        self._elecnest_http: httpx.AsyncClient | None = None
        self.runtimes: dict[str, Runtime] = {}
        self._resolve_api_key: Callable[[LLMProvider], str] | None = None
        self._reloader_scope: anyio.CancelScope | None = None
        self._reloader_task: asyncio.Task[None] | None = None

    async def startup(self, app: FastAPI) -> None:
        """启动扩展、加载注册表、刷新索引、启动热重载后台任务。"""
        await startup_extensions(app)
        self.db = get_database()
        self.storage = get_storage()
        self.llm = get_client()
        self.providers = get_providers()
        self._resolve_api_key = resolve_api_key
        self.mcp_manager = get_manager()
        self.script_executor = ScriptExecutor(self.settings)
        self.workspaces = WorkspaceManager(self.settings)
        self.files = FileService(self.settings, self.db, self.storage)
        self.registry = AgentRegistry(self.settings, get_registry())
        await self.registry.refresh()
        self.catalog = AssistantCatalog(self.registry)
        self.conversation_service = ConversationService(self.db, self.settings, self.catalog)
        self.elecnest = self._build_elecnest()
        self.auth = AuthService(
            self.settings,
            self.db,
            self.conversation_service,
            self.files,
            elecnest=self.elecnest,
        )
        reloader = HotReloader(self.registry, self.settings)
        scope = anyio.CancelScope()
        self._reloader_scope = scope
        # pragma: 简化 — 单常驻协程在 anyio v4 无顶层 create_task；任务组宿主模式
        # 跨任务退出会触发 cancel-scope 跨任务报错，宿主任务内嵌任务组取消时又会
        # 死锁（同 protocol/emitter.py 注释），故用 asyncio.create_task + 显式
        # 取消/join 管理生命周期（CLAUDE.md §4 禁令针对「裸建任务不管理生命周期」）。
        self._reloader_task = asyncio.create_task(self._run_reloader(reloader, scope))

    async def shutdown(self, app: FastAPI) -> None:
        """释放会话运行时 MCP 引用、停止热重载、逆序关停扩展。"""
        for runtime in self.runtimes.values():
            await runtime.close()
        self.runtimes.clear()
        if self._reloader_task is not None and self._reloader_scope is not None:
            self._reloader_scope.cancel()
            await self._reloader_task
            self._reloader_task = None
            self._reloader_scope = None
        if self._elecnest_http is not None:
            await self._elecnest_http.aclose()
            self._elecnest_http = None
            self.elecnest = None
        await shutdown_extensions(app)

    async def _run_reloader(self, reloader: HotReloader, scope: anyio.CancelScope) -> None:
        """常驻协程宿主：取消作用域进入/退出在同一任务，由 shutdown 跨任务取消。"""
        with scope:
            await reloader.run()

    def assistant_catalog(self) -> AssistantCatalog:
        """助手目录（复用注册表当前索引，热重载后即最新）。"""
        assert self.catalog is not None
        return self.catalog

    def _build_elecnest(self) -> ElecnestSSOClient | None:
        """统一登录客户端：开关关闭返回 None（/auth/login/elecnest 返回 400）。"""
        if not self.settings.elecnest_sso_enabled:
            return None
        self._elecnest_http = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.elecnest_sso_timeout_seconds)
        )
        return ElecnestSSOClient(self.settings, self._elecnest_http)

    def get_runtime(self, session_id: str) -> Runtime:
        """获取（或创建）会话级运行时。创建后复用同一工具代理。"""
        runtime = self.runtimes.get(session_id)
        if runtime is None:
            assert self.providers is not None
            assert self.mcp_manager is not None
            assert self.script_executor is not None
            assert self.workspaces is not None
            assert self.files is not None
            assert self.registry is not None
            assert self.db is not None
            assert self.llm is not None
            assert self._resolve_api_key is not None
            runtime = Runtime(
                settings=self.settings,
                workspaces=self.workspaces,
                files=self.files,
                registry=self.registry,
                llm=self.llm,
                providers=self.providers,
                resolve_api_key=self._resolve_api_key,
                mcp_manager=self.mcp_manager,
                script_executor=self.script_executor,
                db=self.db,
                history=self.conversation_service,  # 会话记忆 L1：首轮历史上下文恢复
            )
            self.runtimes[session_id] = runtime
        return runtime

    async def discard_runtime(self, session_id: str) -> bool:
        """释放并移除会话运行时；存在则关停并回收 MCP 引用，返回 True；否则 False。"""
        runtime = self.runtimes.pop(session_id, None)
        if runtime is not None:
            await runtime.close()
            return True
        return False


def get_services(request: Request) -> AppServices:
    """FastAPI 依赖：取应用级服务容器。"""
    services = request.app.state.services
    assert isinstance(services, AppServices)
    return services
