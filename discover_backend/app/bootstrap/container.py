"""组合根装配：构造应用服务容器 + 生命周期启停顺序。

本模块是唯一允许「同时认识 infrastructure 访问器、application 服务与
domain 端口实现」的地方；只做装配，不承载业务判断。
"""

from __future__ import annotations

import asyncio
import logging

import anyio
import httpx
from fastapi import FastAPI

from app.application.assistant.catalog import AssistantCatalog
from app.application.context.adapters import ConversationContextAdapter
from app.application.conversation.service import ConversationService
from app.application.file.service import FileService
from app.application.identity.service import AuthService
from app.application.services import AppServices
from app.application.skill_package import DatabasePackageSource, SkillPackageService
from app.bootstrap.extensions import shutdown_extensions, startup_extensions
from app.environment.context import ContextAssembler
from app.environment.mcp.accessors import get_manager, get_registry
from app.environment.storage.accessors import get_storage
from app.environment.tools.script_executor import ScriptExecutor
from app.environment.workspace.service import WorkspaceManager
from app.harness.skill.hot_reload import HotReloader
from app.harness.skill.loader import AgentLoader
from app.harness.skill.registry import AgentRegistry
from app.infrastructure.database.accessors import get_database
from app.infrastructure.database.engine import Database
from app.infrastructure.redis.client import get_cache
from app.infrastructure.redis.session_store import RedisSessionStore
from app.infrastructure.sso.elecnest import ElecnestSSOClient
from app.llm.accessors import get_client, get_providers, resolve_api_key

logger = logging.getLogger(__name__)


async def start_services(services: AppServices, app: FastAPI) -> None:
    """启动扩展 → 构造应用服务 → 刷新技能索引 → 启动热重载后台任务。"""
    await startup_extensions(app)
    _build_services(services, get_database())
    assert services.registry is not None
    await services.registry.refresh()
    reloader = HotReloader(services.registry, services.settings)
    scope = anyio.CancelScope()
    services.reloader_scope = scope
    # pragma: 简化 — 单常驻协程在 anyio v4 无顶层 create_task；任务组宿主模式
    # 跨任务退出会触发 cancel-scope 跨任务报错，宿主任务内嵌任务组取消时又会
    # 死锁（同 emitter.py 注释），故用 asyncio.create_task + 显式取消/join 管理
    # 生命周期（CLAUDE.md §4 禁令针对「裸建任务不管理生命周期」）。
    services.reloader_task = asyncio.create_task(_run_reloader(reloader, scope))


async def stop_services(services: AppServices, app: FastAPI) -> None:
    """停止热重载 → 释放 SSO 连接池 → 逆序关停扩展。"""
    if services.reloader_task is not None and services.reloader_scope is not None:
        services.reloader_scope.cancel()
        await services.reloader_task
        services.reloader_task = None
        services.reloader_scope = None
    if services.elecnest_http is not None:
        await services.elecnest_http.aclose()
        services.elecnest_http = None
        services.elecnest = None
    await shutdown_extensions(app)


def _build_services(services: AppServices, database: Database) -> None:
    """从扩展访问器取客户端并组装应用服务（唯一装配点）。"""
    services.db = database
    services.storage = get_storage()
    services.llm = get_client()
    services.providers = get_providers()
    services.resolve_api_key = resolve_api_key
    services.mcp_manager = get_manager()
    services.script_executor = ScriptExecutor(services.settings)
    services.workspaces = WorkspaceManager(services.settings)
    services.files = FileService(services.settings, database, services.storage)
    mcp_registry = get_registry()
    if services.settings.agent_package_source == "database":
        loader = AgentLoader(services.settings, mcp_registry)
        services.skill_packages = SkillPackageService(
            services.settings, database, services.storage, loader
        )
        services.registry = AgentRegistry(
            services.settings,
            mcp_registry,
            source=DatabasePackageSource(
                loader,
                services.skill_packages,
                services.settings.agents_root_dir.resolve(),
            ),
        )
    else:
        services.registry = AgentRegistry(services.settings, mcp_registry)
    services.catalog = AssistantCatalog(services.registry)
    services.conversation_service = ConversationService(
        database, services.settings, services.catalog
    )
    services.context_assembler = ContextAssembler(
        conversation=ConversationContextAdapter(services.conversation_service)
    )
    services.elecnest = _build_elecnest(services)
    # Redis 会话层：原本地登录（兼容回退）签发令牌对后写会话，受保护请求对本地
    # 令牌校验访问会话；平台令牌路径不写本地会话（只验签）
    services.auth = AuthService(
        services.settings,
        database,
        services.conversation_service,
        services.files,
        elecnest=services.elecnest,
        sessions=RedisSessionStore(get_cache()),
    )


def _build_elecnest(services: AppServices) -> ElecnestSSOClient | None:
    """统一登录客户端：开关关闭返回 None（/auth/login/elecnest 返回 400）。"""
    if not services.settings.elecnest_sso_enabled:
        return None
    services.elecnest_http = httpx.AsyncClient(
        timeout=httpx.Timeout(services.settings.elecnest_sso_timeout_seconds)
    )
    return ElecnestSSOClient(services.settings, services.elecnest_http)


async def _run_reloader(reloader: HotReloader, scope: anyio.CancelScope) -> None:
    """常驻协程宿主：取消作用域进入/退出在同一任务，由 shutdown 跨任务取消。"""
    with scope:
        await reloader.run()


__all__ = ["AppServices", "start_services", "stop_services"]
