"""应用服务容器：生命周期内单例集合（不含 FastAPI 依赖与装配顺序）。

只承载「一次装配、全局复用」的服务引用与访问方法；具体构造与启停顺序由
组合根 `app/bootstrap/container.py` 负责（依赖方向：bootstrap → application）。
interfaces 层经 `app/interfaces/http/deps.py::get_services` 取本对象。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import anyio
import httpx

from app.application.assistant.catalog import AssistantCatalog
from app.application.conversation.service import ConversationService
from app.application.file.service import FileService
from app.application.identity.service import AuthService
from app.application.skill_package.service import SkillPackageService
from app.config.loader import LLMProvider
from app.config.settings import Settings
from app.environment.context import ContextAssembler
from app.environment.mcp.manager import MCPManager
from app.environment.storage.base import BaseStorage
from app.environment.tools.script_executor import ScriptExecutor
from app.environment.workspace.service import WorkspaceManager
from app.harness.checkpoint.memory import (
    MemoryEventLog,
    MemoryRunLease,
    MemorySnapshotStore,
)
from app.harness.service import RunService
from app.harness.skill.registry import AgentRegistry
from app.harness.turn import ActiveTurnRegistry
from app.infrastructure.database.engine import Database
from app.infrastructure.sso.elecnest import ElecnestSSOClient
from app.llm.client import LLMClient
from app.llm.providers import ProviderRegistry


class AppServices:
    """平台服务容器：由组合根构造并在 lifespan 中启停。"""

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
        self.skill_packages: SkillPackageService | None = None
        self.catalog: AssistantCatalog | None = None
        self.conversation_service: ConversationService | None = None
        # Agent 上下文装配器（agent-context-plane-spec §5.1）：只注入来源端口适配器，
        # 具体存储经 ConversationService / FileService 访问
        self.context_assembler: ContextAssembler | None = None
        self.auth: AuthService | None = None
        self.registry: AgentRegistry | None = None
        self.elecnest: ElecnestSSOClient | None = None
        # SSO 客户端共用的 httpx 连接池（组合根负责关闭）
        self.elecnest_http: httpx.AsyncClient | None = None
        # Run 生命周期服务（v2 §16/§17）：checkpoint 内存实现，DB/Redis store 接线后替换
        self.run_service = RunService(
            snapshots=MemorySnapshotStore(),
            events=MemoryEventLog(),
            lease=MemoryRunLease(),
            owner_id="api",
        )
        # 进行中回合句柄注册表（stop 接口据此取消回合；回合退出后注销；
        # 陈旧句柄按 TTL 自动回收，防客户端断连泄漏会话锁）
        self.active_turns = ActiveTurnRegistry(ttl_seconds=settings.active_turn_ttl_seconds)
        self.resolve_api_key: Callable[[LLMProvider], str] | None = None
        self.reloader_scope: anyio.CancelScope | None = None
        self.reloader_task: asyncio.Task[None] | None = None

    def assistant_catalog(self) -> AssistantCatalog:
        """助手目录（复用注册表当前索引，热重载后即最新）。"""
        assert self.catalog is not None
        return self.catalog


__all__ = ["AppServices"]
