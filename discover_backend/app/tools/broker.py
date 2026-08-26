"""工具代理（L2，tool-broker-spec）：三级目录、分发、并发、截断。

每个会话一个 ToolBroker 实例。目录在技能激活时构建（Tier 0 + Tier 1），
MCP 启动时扩充（Tier 2），describe_tool 运行时扩展暴露集合。
分发从不向上抛异常，一律返回 ToolResult；失败结果必含面向模型的建议。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Protocol

import anyio
from pydantic import BaseModel, Field

from app.config.settings import Settings, SideEffectType
from app.errors.base import (
    ErrorCategory,
    PlatformError,
    RegistryValidationError,
)
from app.history.repo import HistoryStore
from app.llm.models import ChatToolSpec
from app.protocol.sanitize import sanitize_tool_args, truncate
from app.registry.assemble import AssemblyPlan
from app.tools.descriptor import (
    ToolDescriptor,
    ToolSource,
    mcp_qualified_name,
    script_qualified_name,
    to_chat_tool_spec,
)
from app.tools.mcp_client import MCPClient
from app.tools.script_executor import ScriptExecution

logger = logging.getLogger(__name__)

_DEFAULT_SCRIPT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"input": {"type": "string"}},
    "required": ["input"],
}
_META_QUERY_LIMIT = 20
_LOG_ARGS_SUMMARY_CHARS = 300


class MCPManagerPort(Protocol):
    """工具代理依赖的 MCP 管理器抽象（DIP）。"""

    async def acquire(self, server_id: str) -> MCPClient: ...
    def release(self, server_id: str) -> None: ...
    def concurrency_limit(self, server_id: str) -> int: ...


class ScriptExecutorPort(Protocol):
    """工具代理依赖的脚本执行器抽象（DIP）。"""

    async def run(
        self,
        *,
        host_script: Path,
        skill_dir: Path,
        workspace: Path,
        args: dict[str, object],
        env_whitelist: list[str],
        timeout_seconds: float,
    ) -> ScriptExecution: ...


class ToolCallRequest(BaseModel):
    """一次工具调用请求。"""

    call_id: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具调用结果（tool-broker-spec §11）。失败时建议字段必须非空。"""

    call_id: str
    tool_name: str
    ok: bool
    content: str = ""
    error_category: ErrorCategory | None = None
    message: str = ""
    suggestion: str | None = None
    duration_ms: int = 0
    truncated: bool = False
    log_path: str | None = None
    produced_files: list[str] = Field(default_factory=list)


class ToolActivation(BaseModel):
    """技能激活结果：启动服务、降级项、失败项。"""

    ok: bool
    core_count: int = 0
    catalog_size: int = 0
    started_services: list[str] = Field(default_factory=list)
    degraded_services: list[str] = Field(default_factory=list)
    degrade_notes: list[str] = Field(default_factory=list)
    failed_required: list[str] = Field(default_factory=list)
    reason: str | None = None


class ToolHit(BaseModel):
    """检索命中项：只含名称、来源与简要说明，不含参数约束（§9）。"""

    qualified_name: str
    description: str
    source: ToolSource


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _safe_filename(name: str) -> str:
    """工具名 / call_id 转安全文件名：替换 Windows 保留字符并限长。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name)[:80]


def _read_json(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryValidationError(f"入参约束文件非法：{path}") from exc
    return data if isinstance(data, dict) else {}


def _similarity(left: str, right: str) -> int:
    """命名空间分片重叠度，用于相近工具候选。"""
    left_parts = set(left.split("."))
    right_parts = set(right.split("."))
    return len(left_parts & right_parts)


def _extract_upsert(stdout: str) -> tuple[dict[str, object] | None, str]:
    """从脚本 stdout 提取 `_upsert` 回写载荷，并从模型可见内容中移除。"""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None, stdout
    if not isinstance(data, dict):
        return None, stdout
    upsert = data.pop("_upsert", None)
    if not isinstance(upsert, dict):
        return None, stdout
    return upsert, json.dumps(data, ensure_ascii=False, indent=2)


def _extract_section(text: str, section: str) -> str:
    """按标题分段，返回命中的段；未命中返回全文。"""
    active = "开头"
    sections: dict[str, list[str]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            active = stripped.lstrip("#").strip()
        sections.setdefault(active, []).append(line)
    for key, body in sections.items():
        if section in key:
            return "\n".join(body)
    return text


class ToolBroker:
    """工具代理：每会话一个实例。三级目录 + 分发 + 并发 + 截断。"""

    def __init__(
        self,
        *,
        settings: Settings,
        mcp_manager: MCPManagerPort,
        script_executor: ScriptExecutorPort,
        history_store: HistoryStore | None = None,
    ) -> None:
        self._settings = settings
        self._mcp_manager = mcp_manager
        self._script_executor = script_executor
        self._history_store = history_store
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._exposed: set[str] = set()
        self._service_slots: dict[str, anyio.Semaphore] = {}
        self._clients: dict[str, MCPClient] = {}
        self._skill_dir: Path | None = None
        self._workspace: Path | None = None
        self._session_id: str = ""
        self._env_whitelist: list[str] = []
        self._loaded_docs: set[str] = set()
        self._activated = False
        self._log_file_count = 0
        self._log_swept = False
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

    async def activate(
        self,
        *,
        plan: AssemblyPlan,
        skill_dir: Path,
        workspace: Path,
        session_id: str,
    ) -> ToolActivation:
        """技能激活：构建 Tier1 脚本工具、启动 MCP、扩充 Tier2。"""
        if self._activated:
            await self.close()  # 换技能重新装配前释放旧引用
        self._skill_dir = skill_dir
        self._workspace = workspace
        self._session_id = session_id
        self._log_file_count = 0
        if not self._log_swept:
            await self._sweep_stale_logs()
            self._log_swept = True
        self._env_whitelist = plan.env_whitelist
        self._service_slots = {}
        self._clients = {}
        await self._add_script_tools(plan, skill_dir)
        started: list[str] = []
        degraded: list[str] = []
        degrade_notes: list[str] = []
        failed_required: list[str] = []
        for server_id in plan.required_mcp_servers:
            try:
                client = await self._mcp_manager.acquire(server_id)
            except PlatformError:
                failed_required.append(server_id)
                continue
            await self._add_mcp_tools(server_id, client, plan.core_tool_names)
            self._clients[server_id] = client
            started.append(server_id)
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
                client = await self._mcp_manager.acquire(server_id)
            except PlatformError:
                degraded.append(server_id)
                degrade_notes.append(
                    plan.mcp_degrade_notes.get(server_id) or "数据源不可用，已降级"
                )
                continue
            await self._add_mcp_tools(server_id, client, plan.core_tool_names)
            self._clients[server_id] = client
            started.append(server_id)
        self._activated = True
        return ToolActivation(
            ok=True,
            core_count=self._core_count(),
            catalog_size=len(self._descriptors),
            started_services=started,
            degraded_services=degraded,
            degrade_notes=degrade_notes,
        )

    async def _add_script_tools(self, plan: AssemblyPlan, skill_dir: Path) -> None:
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
        for tool in tools:
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
        self._activated = False

    # ---- 对外查询 ----
    def get_descriptor(self, qualified_name: str) -> ToolDescriptor | None:
        """按限定名取描述符（供运行时读取副作用与参数约束）。"""
        return self._descriptors.get(qualified_name)

    def exposed_tools(self) -> list[ChatToolSpec]:
        """当前暴露集合的工具描述（Tier 0 + Tier 1 + 已 describe 的 Tier 2）。"""
        names = sorted(n for n in self._exposed if n in self._descriptors)
        return [to_chat_tool_spec(self._descriptors[n]) for n in names]

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
            self._failure(
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
                    results[index] = self._failure(
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
            return self._not_found(call)
        if descriptor.source == ToolSource.META:
            return await self._handle_meta(descriptor, call)
        if descriptor.source == ToolSource.SCRIPT:
            return await self._dispatch_script(descriptor, call)
        return await self._dispatch_mcp(descriptor, call)

    # ---- 元工具 ----
    async def _handle_meta(self, descriptor: ToolDescriptor, call: ToolCallRequest) -> ToolResult:
        if descriptor.short_name == "search_tools":
            query = str(call.arguments.get("query", ""))
            limit = 10
            raw_limit = call.arguments.get("limit")
            if isinstance(raw_limit, int):
                limit = min(raw_limit, _META_QUERY_LIMIT)
            hits = self.search_tools(query, limit)
            content = "\n".join(
                f"- {hit.qualified_name}（{hit.source.value}）{hit.description}" for hit in hits
            )
            return self._success(call, content or "未找到匹配工具", duration_ms=0)
        if descriptor.short_name == "describe_tool":
            target = str(call.arguments.get("qualified_name", ""))
            found = self._descriptors.get(target)
            if found is None:
                candidates = self._nearest(target)
                return ToolResult(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    ok=False,
                    error_category=ErrorCategory.NOT_FOUND,
                    message=f"工具不存在：{target}",
                    suggestion=f"相近候选：{', '.join(candidates)}"
                    if candidates
                    else "先用 search_tools 检索",
                )
            self._exposed.add(target)  # 副作用：加入本会话暴露集合
            return self._success(call, found.model_dump_json(), duration_ms=0)
        if descriptor.short_name == "read_reference":
            return await self._handle_read_reference(call)
        return self._failure(
            call, category=ErrorCategory.SERVER, message="未知元工具", suggestion="检查工具名"
        )

    async def _handle_read_reference(self, call: ToolCallRequest) -> ToolResult:
        if self._skill_dir is None:
            return self._failure(
                call, category=ErrorCategory.SERVER, message="技能未激活", suggestion="先激活技能"
            )
        rel = str(call.arguments.get("path", ""))
        section = call.arguments.get("section")
        reference_root = (self._skill_dir / "references").resolve()
        if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            return self._failure(
                call,
                category=ErrorCategory.INVALID_ARGUMENT,
                message="路径非法",
                suggestion="路径须相对 references/ 且无穿越",
            )
        target = (reference_root / rel).resolve()
        if not target.is_relative_to(reference_root):
            return self._failure(
                call,
                category=ErrorCategory.INVALID_ARGUMENT,
                message="路径越界",
                suggestion="只允许读取当前技能 references/ 下的文档",
            )
        if not target.is_file():
            return self._failure(
                call,
                category=ErrorCategory.NOT_FOUND,
                message=f"文档不存在：{rel}",
                suggestion="核对 references/ 下的文件名",
            )
        if rel in self._loaded_docs:
            return self._success(call, "已在上下文", duration_ms=0)
        text = await anyio.to_thread.run_sync(_read_doc, target)
        if section is not None:
            text = _extract_section(text, str(section))
        self._loaded_docs.add(rel)
        return self._success(call, truncate(text, max_length=2000), duration_ms=0)

    # ---- MCP 分发 ----
    async def _dispatch_mcp(self, descriptor: ToolDescriptor, call: ToolCallRequest) -> ToolResult:
        client = self._clients.get(descriptor.namespace)
        if client is None:
            logger.error(
                "MCP 工具 %s 服务 %s 未激活（call_id=%s）",
                call.tool_name,
                descriptor.namespace,
                call.call_id,
            )
            return self._failure(
                call,
                category=ErrorCategory.SERVER,
                message="MCP 服务未激活",
                suggestion="该服务未在当前会话激活",
            )
        semaphore = self._service_slots.get(descriptor.namespace) or anyio.Semaphore(1)
        logger.debug(
            "调用 MCP 工具 %s（call_id=%s），入参：%s",
            call.tool_name,
            call.call_id,
            sanitize_tool_args(
                json.dumps(call.arguments, ensure_ascii=False), max_length=_LOG_ARGS_SUMMARY_CHARS
            ),
        )
        start = time.perf_counter()
        async with semaphore:
            try:
                result = await client.call_tool(descriptor.short_name, call.arguments)
            except PlatformError as exc:
                return self._failure_from_error(call, descriptor, exc, start)
        duration_ms = int((time.perf_counter() - start) * 1000)
        if result.is_error:
            logger.error(
                "MCP 工具 %s 执行失败（%dms，call_id=%s）：%s",
                call.tool_name,
                duration_ms,
                call.call_id,
                result.content or "工具执行失败",
            )
            return self._failure(
                call,
                category=ErrorCategory.SERVER,
                message=result.content or "工具执行失败",
                suggestion="调整参数或换用其他工具",
                duration_ms=duration_ms,
            )
        content = result.content or "未找到相关结果"
        logger.debug(
            "MCP 工具 %s 成功（%dms，call_id=%s）", call.tool_name, duration_ms, call.call_id
        )
        return await self._finish_success(call, content, duration_ms)

    # ---- 脚本分发 ----
    async def _dispatch_script(
        self, descriptor: ToolDescriptor, call: ToolCallRequest
    ) -> ToolResult:
        if (
            self._workspace is None
            or self._skill_dir is None
            or descriptor.host_script_path is None
        ):
            logger.error("脚本工具 %s 工作区未就绪（call_id=%s）", call.tool_name, call.call_id)
            return self._failure(
                call,
                category=ErrorCategory.SERVER,
                message="工作区未就绪",
                suggestion="检查会话装配状态",
            )
        args: dict[str, object] = call.arguments
        history_store = self._history_store
        if (
            descriptor.script_decl is not None
            and descriptor.script_decl.history_store
            and history_store is not None
        ):
            args = {**call.arguments, "history": await history_store.load_history()}
        timeout = descriptor.timeout_seconds or self._settings.tool_default_timeout_seconds
        logger.debug(
            "执行脚本工具 %s（call_id=%s），超时 %.1fs，入参：%s",
            call.tool_name,
            call.call_id,
            timeout,
            sanitize_tool_args(
                json.dumps(args, ensure_ascii=False), max_length=_LOG_ARGS_SUMMARY_CHARS
            ),
        )
        start = time.perf_counter()
        try:
            execution = await self._script_executor.run(
                host_script=Path(descriptor.host_script_path),
                skill_dir=self._skill_dir,
                workspace=self._workspace,
                args=args,
                env_whitelist=self._env_whitelist,
                timeout_seconds=timeout,
            )
        except PlatformError as exc:
            return self._failure_from_error(call, descriptor, exc, start)
        duration_ms = int((time.perf_counter() - start) * 1000)
        if execution.timed_out:
            logger.error(
                "脚本工具 %s 执行超时（%dms，call_id=%s）",
                call.tool_name,
                duration_ms,
                call.call_id,
            )
            return self._failure(
                call,
                category=ErrorCategory.TIMEOUT,
                message="脚本执行超时",
                suggestion="缩小输入或分批",
                duration_ms=duration_ms,
            )
        if execution.exit_code != 0:
            message = self._script_failure_message(execution)
            logger.error(
                "脚本工具 %s 执行失败（exit=%d，%dms，call_id=%s）：%s",
                call.tool_name,
                execution.exit_code,
                duration_ms,
                call.call_id,
                message,
            )
            logger.debug(
                "脚本工具 %s stderr 尾部：%s", call.tool_name, execution.stderr_tail or "（无）"
            )
            return self._failure(
                call,
                category=ErrorCategory.SCRIPT,
                message=message,
                suggestion="检查输入参数或脚本输出",
                duration_ms=duration_ms,
            )
        content = execution.stdout or "（脚本无输出）"
        if (
            descriptor.script_decl is not None
            and descriptor.script_decl.history_store
            and history_store is not None
        ):
            upsert, content = _extract_upsert(content)
            if upsert is not None:
                await history_store.upsert_clue(upsert)
        produced = [str(path.relative_to(self._workspace)) for path in execution.produced_files]
        logger.debug(
            "脚本工具 %s 成功（%dms，stdout %d 字符，产物 %s，call_id=%s）",
            call.tool_name,
            duration_ms,
            len(execution.stdout),
            produced or "（无）",
            call.call_id,
        )
        result = await self._finish_success(call, content, duration_ms)
        return result.model_copy(update={"produced_files": produced})

    # ---- 结果构造 ----
    def _script_failure_message(self, execution: ScriptExecution) -> str:
        """脚本失败诊断：优先 stdout 错误载荷（契约规定失败信息走 stdout JSON），
        次选 stderr 尾部，最后回落退出码占位。截断至输出阈值防上下文撑爆。"""
        limit = self._settings.tool_output_truncate_chars
        stdout = execution.stdout.strip()
        if stdout:
            try:
                parsed = json.loads(stdout)
                if isinstance(parsed, dict) and parsed.get("error"):
                    return truncate(str(parsed["error"]), max_length=limit)
            except json.JSONDecodeError:
                pass
            if len(stdout) <= limit:
                return truncate(stdout, max_length=limit)
        if execution.stderr_tail:
            return truncate(execution.stderr_tail, max_length=limit)
        return f"脚本退出码非 0：{execution.exit_code}"

    async def _finish_success(
        self, call: ToolCallRequest, content: str, duration_ms: int
    ) -> ToolResult:
        truncated_content, truncated = self._truncate_content(content)
        # 仅截断时落盘完整原文：未截断的输出与 ToolResult.content 逐字一致，写文件是纯冗余。
        log_path = await self._write_full_log(call, content) if truncated else None
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            ok=True,
            content=truncated_content,
            duration_ms=duration_ms,
            truncated=truncated,
            log_path=log_path,
        )

    def _success(self, call: ToolCallRequest, content: str, duration_ms: int) -> ToolResult:
        truncated_content, truncated = self._truncate_content(content)
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            ok=True,
            content=truncated_content,
            duration_ms=duration_ms,
            truncated=truncated,
        )

    def _failure(
        self,
        call: ToolCallRequest,
        *,
        category: ErrorCategory,
        message: str,
        suggestion: str,
        duration_ms: int = 0,
    ) -> ToolResult:
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            ok=False,
            error_category=category,
            message=message,
            suggestion=suggestion,
            duration_ms=duration_ms,
        )

    def _failure_from_error(
        self,
        call: ToolCallRequest,
        descriptor: ToolDescriptor,
        exc: PlatformError,
        start: float,
    ) -> ToolResult:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.error(
            "工具 %s 失败（category=%s，%dms，call_id=%s）：%s",
            call.tool_name,
            exc.category,
            duration_ms,
            call.call_id,
            exc,
        )
        return self._failure(
            call,
            category=exc.category,
            message=str(exc),
            suggestion=self._suggestion_for(exc.category, descriptor.namespace),
            duration_ms=duration_ms,
        )

    def _not_found(self, call: ToolCallRequest) -> ToolResult:
        candidates = self._nearest(call.tool_name)
        logger.warning(
            "工具不在目录：%s（call_id=%s），相近候选：%s",
            call.tool_name,
            call.call_id,
            ", ".join(candidates) or "（无）",
        )
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            ok=False,
            error_category=ErrorCategory.NOT_FOUND,
            message=f"工具不在目录：{call.tool_name}",
            suggestion=f"相近候选：{', '.join(candidates)}"
            if candidates
            else "先用 search_tools 检索",
        )

    def _nearest(self, name: str, k: int = 3) -> list[str]:
        scored = sorted(self._descriptors, key=lambda n: -_similarity(n, name))
        return [n for n in scored if n != name][:k]

    def _truncate_content(self, content: str) -> tuple[str, bool]:
        limit = self._settings.tool_output_truncate_chars
        if len(content) <= limit:
            return content, False
        return truncate(content, max_length=limit), True

    async def _sweep_stale_logs(self) -> None:
        """清理超过保留期的工具日志会话目录；retention_days <= 0 表示不清理。"""
        retention_days = self._settings.tool_log_retention_days
        root = self._settings.tool_log_root_dir
        if retention_days <= 0 or not root.is_dir():
            return
        cutoff = time.time() - retention_days * 86400
        for child in root.iterdir():
            if not child.is_dir():
                continue
            try:
                stale = child.stat().st_mtime < cutoff
            except OSError:
                continue
            if stale:
                logger.info("清理过期工具日志目录：%s", child)
                await anyio.to_thread.run_sync(_rmtree, child)

    async def _write_full_log(self, call: ToolCallRequest, content: str) -> str | None:
        limit = self._settings.tool_log_max_files_per_session
        if limit > 0 and self._log_file_count >= limit:
            logger.warning("本会话工具日志已达上限 %d，停止落盘（call_id=%s）", limit, call.call_id)
            return None
        name = f"{_safe_filename(call.call_id)}_{_safe_filename(call.tool_name)}.txt"
        path = self._settings.tool_log_root_dir / self._session_id / name
        try:
            await anyio.to_thread.run_sync(_write_text, path, content)
        except OSError:
            return None
        self._log_file_count += 1
        return str(path)

    def _suggestion_for(self, category: ErrorCategory, namespace: str) -> str:
        mapping: dict[ErrorCategory, str] = {
            ErrorCategory.TIMEOUT: "缩小输入或分批",
            ErrorCategory.RATE_LIMIT: "上游限流，稍后重试",
            ErrorCategory.AUTH: f"检查 {namespace or '服务'} 的令牌环境变量",
            ErrorCategory.CONNECTION: "服务连接失败，稍后重试",
            ErrorCategory.SERVER: "服务暂时不可用，走降级通道",
            ErrorCategory.INVALID_ARGUMENT: "按参数约束调整参数后重试",
            ErrorCategory.CONFIG: "检查服务配置",
        }
        return mapping.get(category, "重试或换用其他工具")


def _resolve_script_host(skill_dir: Path, rel: str) -> Path | None:
    candidate = skill_dir / Path(rel)
    if candidate.is_file():
        return candidate
    return None


def _read_doc(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
