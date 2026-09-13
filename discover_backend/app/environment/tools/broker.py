"""工具代理（L2，tool-broker-spec）：三级目录、分发、并发、截断。

每个会话一个 ToolBroker 实例。目录在技能激活时构建（Tier 0 + Tier 1），
MCP 启动时扩充（Tier 2），describe_tool 运行时扩展暴露集合。
分发从不向上抛异常，一律返回 ToolResult；失败结果必含面向模型的建议。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import anyio

from app.config.settings import Settings, SideEffectType
from app.environment.mcp.client import MCPClient
from app.environment.tools.broker_contracts import (
    _DEFAULT_SCRIPT_SCHEMA,
    MCPManagerPort,
    ScriptExecutorPort,
    ToolActivation,
    ToolHit,
    _read_json,
    _resolve_script_host,
)
from app.environment.tools.broker_dispatch import (
    dispatch_mcp,
    dispatch_script,
    failure,
    handle_meta,
    not_found,
)
from app.environment.tools.models import (
    ToolCallRequest,
    ToolDescriptor,
    ToolResult,
    ToolSource,
    mcp_qualified_name,
    script_qualified_name,
    to_chat_tool_spec,
)
from app.environment.tools.plan import ToolActivationPlan
from app.llm.models import ChatToolSpec
from app.shared.errors.base import (
    ErrorCategory,
    PlatformError,
)

logger = logging.getLogger(__name__)


class ToolBroker:
    """工具代理：每会话一个实例。三级目录 + 分发 + 并发 + 截断。"""

    def __init__(
        self,
        *,
        settings: Settings,
        mcp_manager: MCPManagerPort,
        script_executor: ScriptExecutorPort,
    ) -> None:
        self._settings = settings
        self._mcp_manager = mcp_manager
        self._script_executor = script_executor
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._exposed: set[str] = set()
        self._service_slots: dict[str, anyio.Semaphore] = {}
        self._clients: dict[str, MCPClient] = {}
        self._skill_dir: Path | None = None
        self._workspace: Path | None = None
        self._session_id: str = ""
        self._account_id: str = ""
        self._env_whitelist: list[str] = []
        self._loaded_docs: set[str] = set()
        self._degraded_servers: set[str] = set()
        self._activated = False
        self._install_meta_tools()

    # ---- 目录构建 ----
    def _install_meta_tools(self) -> None:
        specs: list[tuple[str, str, dict[str, object]]] = [
            (
                "search_tools",
                "按查询检索工具目录，返回名称与简要说明",
                {"query": {"type": "string"}, "limit": {"type": "integer"}},
            ),
            (
                "describe_tool",
                "返回指定工具的完整参数约束，并加入本会话可用工具",
                {"qualified_name": {"type": "string"}},
            ),
            (
                "read_reference",
                "按需读取当前技能的参考文档",
                {"path": {"type": "string"}, "section": {"type": "string"}},
            ),
        ]
        for name, description, properties in specs:
            descriptor = ToolDescriptor(
                qualified_name=name,
                short_name=name,
                namespace="",
                description=description,
                parameters={"type": "object", "properties": properties},
                source=ToolSource.META,
                tier=0,
                source_ref="meta",
            )
            self._descriptors[name] = descriptor
            self._exposed.add(name)

    async def _acquire_with_retry(self, server_id: str) -> MCPClient:
        """获取 MCP 客户端：短暂不可用时按配置有界退避重试。

        本地 MCP 服务（如 tencent_mcp）启动慢，单次 acquire 失败即拒绝激活会让服务
        稍后启动时仍需整轮重试。此处最多重试 retry_attempts 次，退避间隔逐次累加；
        重试耗尽仍失败则抛出最后一次异常，由 activate 归入 failed_required（仍拒绝激活，
        规范 mcp-integration-spec §8）。
        """
        attempts = self._settings.mcp_acquire_retry_attempts
        backoff = self._settings.mcp_acquire_retry_backoff_seconds
        last_exc: PlatformError | None = None
        for attempt in range(attempts):
            try:
                return await self._mcp_manager.acquire(server_id)
            except PlatformError as exc:
                last_exc = exc
                if attempt + 1 < attempts:
                    logger.warning(
                        "MCP 依赖获取失败，将重试：server=%s 第 %d/%d 次",
                        server_id,
                        attempt + 1,
                        attempts,
                        exc_info=True,
                    )
                    await anyio.sleep(backoff * (attempt + 1))
        assert last_exc is not None
        raise last_exc

    async def activate(
        self,
        *,
        plan: ToolActivationPlan,
        skill_dir: Path,
        workspace: Path,
        session_id: str,
        account_id: str,
    ) -> ToolActivation:
        """技能激活：构建 Tier1 脚本工具、启动 MCP、扩充 Tier2。"""
        if self._activated:
            await self.close()  # 换技能重新装配前释放旧引用
        self._skill_dir = skill_dir
        self._workspace = workspace
        self._session_id = session_id
        self._account_id = account_id
        self._env_whitelist = plan.env_whitelist
        self._service_slots = {}
        self._clients = {}
        self._degraded_servers = set()
        await self._add_script_tools(plan, skill_dir)
        started: list[str] = []
        degraded: list[str] = []
        degrade_notes: list[str] = []
        failed_required: list[str] = []
        acquired: set[str] = set()
        for server_id in plan.required_mcp_servers:
            try:
                client = await self._acquire_with_retry(server_id)
            except PlatformError:
                failed_required.append(server_id)
                continue
            await self._add_mcp_tools(server_id, client, plan.core_tool_names)
            self._clients[server_id] = client
            started.append(server_id)
            acquired.add(server_id)
        if failed_required:
            for server_id in started:
                self._mcp_manager.release(server_id)
            return ToolActivation(
                ok=False,
                core_count=self._core_count(),
                catalog_size=len(self._descriptors),
                failed_required=failed_required,
                reason="必需 MCP 依赖不可用，拒绝激活",
            )
        for server_id in plan.optional_mcp_servers:
            try:
                client = await self._acquire_with_retry(server_id)
            except PlatformError:
                degraded.append(server_id)
                degrade_notes.append(
                    plan.mcp_degrade_notes.get(server_id) or "数据源不可用，已降级"
                )
                continue
            await self._add_mcp_tools(server_id, client, plan.core_tool_names)
            self._clients[server_id] = client
            started.append(server_id)
            acquired.add(server_id)
        # 能力依赖：主备切换（failover）——候选服务器按注册表顺序尝试，首个可用者生效。
        # 主候选全部不可用且注册表声明 fallback 能力时，尝试 fallback 候选服务器；
        # 命中则视为「已降级至 fallback 能力」，降级说明由系统生成（不来自技能清单）。
        for cap in plan.capabilities:
            cap_failures: list[str] = []
            activated = False
            if cap.strategy == "all":
                # 全部候选激活：各自作为独立工具进目录，调用哪个由模型（re-act）决定，
                # 不做主备切换也不做降级。单候选失败仅降级该候选，不影响其余。
                for server_id in cap.candidate_servers:
                    if server_id in acquired:
                        activated = True
                        continue
                    try:
                        client = await self._acquire_with_retry(server_id)
                    except PlatformError:
                        cap_failures.append(server_id)
                        degraded.append(server_id)
                        degrade_notes.append(cap.degrade_note or "数据源不可用，已跳过")
                        continue
                    await self._add_mcp_tools(server_id, client, cap.core_tools)
                    self._clients[server_id] = client
                    started.append(server_id)
                    acquired.add(server_id)
                    activated = True
                if not activated and cap.required:
                    failed_required.extend(cap_failures)
                continue
            for server_id in cap.candidate_servers:
                if server_id in acquired:
                    activated = True
                    break
                try:
                    client = await self._acquire_with_retry(server_id)
                except PlatformError:
                    cap_failures.append(server_id)
                    degraded.append(server_id)
                    degrade_notes.append(cap.degrade_note or "数据源不可用，已切换备用通道")
                    continue
                await self._add_mcp_tools(server_id, client, cap.core_tools)
                self._clients[server_id] = client
                started.append(server_id)
                acquired.add(server_id)
                activated = True
                break
            if not activated and cap.fallback_servers:
                for server_id in cap.fallback_servers:
                    if server_id in acquired:
                        activated = True
                        break
                    try:
                        client = await self._acquire_with_retry(server_id)
                    except PlatformError:
                        cap_failures.append(server_id)
                        degraded.append(server_id)
                        degrade_notes.append(cap.degrade_note or "数据源不可用，已切换备用通道")
                        continue
                    await self._add_mcp_tools(server_id, client, cap.core_tools)
                    self._clients[server_id] = client
                    started.append(server_id)
                    acquired.add(server_id)
                    activated = True
                    break
                if activated and cap.fallback_capability is not None:
                    degraded.append(cap.capability)
                    degrade_notes.append(
                        f"能力 {cap.capability} 不可用，已降级至能力 {cap.fallback_capability}"
                    )
            if not activated and cap.required:
                failed_required.extend(cap_failures)
        if failed_required:
            for server_id in started:
                self._mcp_manager.release(server_id)
            return ToolActivation(
                ok=False,
                core_count=self._core_count(),
                catalog_size=len(self._descriptors),
                failed_required=failed_required,
                reason="必需依赖不可用，拒绝激活",
            )
        self._activated = True
        return ToolActivation(
            ok=True,
            core_count=self._core_count(),
            catalog_size=len(self._descriptors),
            started_services=started,
            degraded_services=degraded,
            degrade_notes=degrade_notes,
        )

    async def _add_script_tools(self, plan: ToolActivationPlan, skill_dir: Path) -> None:
        for decl in plan.scripts:
            host = _resolve_script_host(skill_dir, decl.path)
            if host is None:
                continue
            name = script_qualified_name(plan.agent_id, plan.skill_id, decl.name)
            if decl.schema_path is not None:
                parameters = await anyio.to_thread.run_sync(
                    _read_json, skill_dir / decl.schema_path
                )
            else:
                parameters = _DEFAULT_SCRIPT_SCHEMA
            timeout = decl.timeout_seconds or self._settings.script_timeout_seconds
            descriptor = ToolDescriptor(
                qualified_name=name,
                short_name=decl.name,
                namespace=f"{plan.agent_id}.{plan.skill_id}.script",
                description=decl.description,
                parameters=parameters,
                source=ToolSource.SCRIPT,
                tier=1,
                side_effect=decl.side_effect,
                timeout_seconds=timeout,
                source_ref=decl.path,
                script_decl=decl,
                host_script_path=str(host),
            )
            self._descriptors[name] = descriptor
            self._exposed.add(name)

    async def _add_mcp_tools(
        self, server_id: str, client: MCPClient, core_tool_names: list[str]
    ) -> None:
        tools = await client.list_tools()
        limit = self._mcp_manager.concurrency_limit(server_id)
        self._service_slots[server_id] = anyio.Semaphore(limit)
        hidden = self._settings.mcp_hidden_tool_names
        # 泛化分发工具（call_tool / call_tools_batch）仅在同服务存在具体工具可替代时剔除；
        # 服务只暴露泛化工具（如 tyc_mcp 天眼查）时保留，否则该服务完全不可用。
        keep_generic = not any(tool.name not in hidden for tool in tools)
        for tool in tools:
            if tool.name in hidden and not keep_generic:
                logger.info(
                    "隐藏 MCP 泛化工具 %s（server=%s），不进入模型可见清单", tool.name, server_id
                )
                continue
            qualified = mcp_qualified_name(server_id, tool.name)
            tier = 1 if tool.name in core_tool_names else 2
            descriptor = ToolDescriptor(
                qualified_name=qualified,
                short_name=tool.name,
                namespace=server_id,
                description=tool.description,
                parameters=tool.input_schema,
                source=ToolSource.MCP,
                tier=tier,
                side_effect=SideEffectType.NETWORK,
                timeout_seconds=client.call_timeout_seconds,
                source_ref=server_id,
            )
            self._descriptors[qualified] = descriptor
            if tier == 1:
                self._exposed.add(qualified)

    def _core_count(self) -> int:
        return sum(1 for d in self._descriptors.values() if d.tier == 1)

    async def close(self) -> None:
        """会话结束：释放全部持有的 MCP 引用并清空状态。"""
        for server_id in self._clients:
            self._mcp_manager.release(server_id)
        self._clients = {}
        self._degraded_servers = set()
        self._activated = False

    def _mark_server_degraded(self, server_id: str) -> None:
        """把 MCP 服务标记为会话级降级：其工具退出模型可见清单，后续调用直接失败。

        计费/鉴权类不可恢复错误触发；区别于连接超时等可重试错误（后者不降级）。
        """
        if server_id in self._degraded_servers:
            return
        self._degraded_servers.add(server_id)
        logger.warning("MCP 服务 %s 已降级，其工具将从模型可见清单移除", server_id)

    # ---- 对外查询 ----
    def get_descriptor(self, qualified_name: str) -> ToolDescriptor | None:
        """按限定名取描述符（供运行时读取副作用与参数约束）。"""
        return self._descriptors.get(qualified_name)

    def exposed_tools(self) -> list[ChatToolSpec]:
        """当前暴露集合的工具描述（Tier 0 + Tier 1 + 已 describe 的 Tier 2）。"""
        names = sorted(
            n
            for n in self._exposed
            if n in self._descriptors
            and self._descriptors[n].namespace not in self._degraded_servers
        )
        return [to_chat_tool_spec(self._descriptors[n]) for n in names]

    def catalog_tool_names(self) -> list[str]:
        """目录中全部已激活工具的限定名（Tier 0 + Tier 1 + Tier 2）。

        阶段白名单应取此全集而非 exposed_tools()：describe_tool 只是按需展开参数约束，
        不构成调用授权（tool-broker-spec §2「允许调用目录中任何已激活服务的工具」）。
        """
        return sorted(
            n
            for n in self._descriptors
            if self._descriptors[n].namespace not in self._degraded_servers
        )

    def search_tools(self, query: str, limit: int = 10) -> list[ToolHit]:
        """关键词匹配检索；只返回名称与简要说明，不含参数约束。"""
        terms = {t for t in re.split(r"[\W_]+", query.lower()) if t}
        scored: list[tuple[int, str]] = []
        for name, descriptor in self._descriptors.items():
            hay = f"{descriptor.short_name} {descriptor.description}".lower()
            score = sum(1 for term in terms if term in hay)
            if score:
                scored.append((score, name))
        scored.sort(key=lambda item: -item[0])
        hits = [
            ToolHit(
                qualified_name=name,
                description=self._descriptors[name].description,
                source=self._descriptors[name].source,
            )
            for _, name in scored[:limit]
        ]
        return hits

    # ---- 分发 ----
    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]:
        """并发分发；结果与入参下标一一对应；异常转为失败结果不向上抛。"""
        logger.debug("工具批次分发开始：%d 个调用", len(calls))
        results: list[ToolResult] = [
            failure(
                self,
                call,
                category=ErrorCategory.SERVER,
                message="执行失败",
                suggestion="重试或换用其他工具",
            )
            for call in calls
        ]
        gate = anyio.Semaphore(self._settings.tool_batch_concurrency)

        async def run_one(index: int, call: ToolCallRequest) -> None:
            async with gate:
                try:
                    results[index] = await self._dispatch(call)
                except Exception:
                    logger.exception(
                        "工具 %s 分发失败（未捕获异常，call_id=%s）", call.tool_name, call.call_id
                    )
                    results[index] = failure(
                        self,
                        call,
                        category=ErrorCategory.SERVER,
                        message="执行失败",
                        suggestion="重试或换用其他工具",
                    )

        async with anyio.create_task_group() as tg:
            for index, call in enumerate(calls):
                tg.start_soon(run_one, index, call)
        logger.debug("工具批次分发完成：%d 个调用", len(results))
        return results

    async def _dispatch(self, call: ToolCallRequest) -> ToolResult:
        logger.debug("分发调用 %s（call_id=%s）", call.tool_name, call.call_id)
        descriptor = self._descriptors.get(call.tool_name)
        if descriptor is None:
            return not_found(self, call)
        if descriptor.source == ToolSource.META:
            return await handle_meta(self, descriptor, call)
        if descriptor.source == ToolSource.SCRIPT:
            return await dispatch_script(self, descriptor, call)
        return await dispatch_mcp(self, descriptor, call)
