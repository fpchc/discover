"""工具分发的职责分离模块（元工具 / MCP / 脚本三条通道）。

单一动机：把 ToolBroker 里「分发 + 结果构造」从目录构建里拆出来，按修改理由
归置（新增分发通道或改失败建议时不再触碰目录 / 激活逻辑）。函数以 broker 为
第一参数，只读/写 ToolBroker 的私有状态；循环依赖经 TYPE_CHECKING 规避。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

import anyio

from app.environment.tools.broker_contracts import (
    _LOG_ARGS_SUMMARY_CHARS,
    _MCP_DEGRADE_CATEGORIES,
    _META_QUERY_LIMIT,
    _coerce_nested_object_args,
    _extract_section,
    _read_doc,
    _similarity,
)
from app.environment.tools.models import (
    ToolCallRequest,
    ToolDescriptor,
    ToolResult,
    ToolSource,
)
from app.environment.tools.script_executor import ScriptExecution
from app.shared.errors.base import ErrorCategory, PlatformError
from app.shared.utils.sanitize import redact_sensitive, sanitize_tool_args, truncate

if TYPE_CHECKING:
    from app.environment.tools.broker import ToolBroker

logger = logging.getLogger(__name__)


async def handle_meta(
    broker: ToolBroker, descriptor: ToolDescriptor, call: ToolCallRequest
) -> ToolResult:
    if descriptor.short_name == "search_tools":
        query = str(call.arguments.get("query", ""))
        limit = 10
        raw_limit = call.arguments.get("limit")
        if isinstance(raw_limit, int):
            limit = min(raw_limit, _META_QUERY_LIMIT)
        hits = broker.search_tools(query, limit)
        content = "\n".join(
            f"- {hit.qualified_name}（{hit.source.value}）{hit.description}" for hit in hits
        )
        return success(broker, call, content or "未找到匹配工具", duration_ms=0)
    if descriptor.short_name == "describe_tool":
        target = str(call.arguments.get("qualified_name", ""))
        found = broker._descriptors.get(target)
        if found is None:
            candidates = nearest(broker, target)
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
        broker._exposed.add(target)  # 副作用：加入本会话暴露集合
        return success(broker, call, found.model_dump_json(), duration_ms=0)
    if descriptor.short_name == "read_reference":
        return await handle_read_reference(broker, call)
    return failure(
        broker, call, category=ErrorCategory.SERVER, message="未知元工具", suggestion="检查工具名"
    )


async def handle_read_reference(broker: ToolBroker, call: ToolCallRequest) -> ToolResult:
    if broker._skill_dir is None:
        return failure(
            broker,
            call,
            category=ErrorCategory.SERVER,
            message="技能未激活",
            suggestion="先激活技能",
        )
    rel = str(call.arguments.get("path", ""))
    section = call.arguments.get("section")
    reference_root = (broker._skill_dir / "references").resolve()
    if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        return failure(
            broker,
            call,
            category=ErrorCategory.INVALID_ARGUMENT,
            message="路径非法",
            suggestion="路径须相对 references/ 且无穿越",
        )
    target = (reference_root / rel).resolve()
    if not target.is_relative_to(reference_root):
        return failure(
            broker,
            call,
            category=ErrorCategory.INVALID_ARGUMENT,
            message="路径越界",
            suggestion="只允许读取当前技能 references/ 下的文档",
        )
    if not target.is_file():
        return failure(
            broker,
            call,
            category=ErrorCategory.NOT_FOUND,
            message=f"文档不存在：{rel}",
            suggestion="核对 references/ 下的文件名",
        )
    if rel in broker._loaded_docs:
        return success(broker, call, "已在上下文", duration_ms=0)
    text = await anyio.to_thread.run_sync(_read_doc, target)
    if section is not None:
        text = _extract_section(text, str(section))
    broker._loaded_docs.add(rel)
    return success(broker, call, truncate(text, max_length=2000), duration_ms=0)


# ---- MCP 分发 ----


async def dispatch_mcp(
    broker: ToolBroker, descriptor: ToolDescriptor, call: ToolCallRequest
) -> ToolResult:
    if descriptor.namespace in broker._degraded_servers:
        return failure(
            broker,
            call,
            category=ErrorCategory.BILLING,
            message="该数据源当前不可用，已降级",
            suggestion="改用其他工具（如联网搜索）兜底，并把缺失字段标注为「未检索到」",
        )
    client = broker._clients.get(descriptor.namespace)
    if client is None:
        logger.error(
            "MCP 工具 %s 服务 %s 未激活（call_id=%s）",
            call.tool_name,
            descriptor.namespace,
            call.call_id,
        )
        return failure(
            broker,
            call,
            category=ErrorCategory.SERVER,
            message="MCP 服务未激活",
            suggestion="该服务未在当前会话激活",
        )
    semaphore = broker._service_slots.get(descriptor.namespace) or anyio.Semaphore(1)
    logger.info(
        "调用 MCP 工具 %s（server=%s，call_id=%s），入参：%s",
        call.tool_name,
        descriptor.namespace,
        call.call_id,
        redact_sensitive(json.dumps(call.arguments, ensure_ascii=False)),
    )
    start = time.perf_counter()
    arguments = _coerce_nested_object_args(descriptor, call.arguments)
    async with semaphore:
        try:
            result = await client.call_tool(descriptor.short_name, arguments)
        except PlatformError as exc:
            return failure_from_error(broker, call, descriptor, exc, start)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if result.is_error:
        logger.error(
            "MCP 工具 %s 执行失败（%dms，server=%s，call_id=%s）：%s",
            call.tool_name,
            duration_ms,
            descriptor.namespace,
            call.call_id,
            result.content or "工具执行失败",
        )
        return failure(
            broker,
            call,
            category=ErrorCategory.SERVER,
            message=result.content or "工具执行失败",
            suggestion="调整参数或换用其他工具",
            duration_ms=duration_ms,
        )
    content = result.content or "未找到相关结果"
    logger.debug(
        "MCP 工具 %s 成功（%dms，server=%s，call_id=%s），返回：%s",
        call.tool_name,
        duration_ms,
        descriptor.namespace,
        call.call_id,
        content,
    )
    return await finish_success(broker, call, content, duration_ms)


# ---- 脚本分发 ----


async def dispatch_script(
    broker: ToolBroker, descriptor: ToolDescriptor, call: ToolCallRequest
) -> ToolResult:
    if (
        broker._workspace is None
        or broker._skill_dir is None
        or descriptor.host_script_path is None
    ):
        logger.error("脚本工具 %s 工作区未就绪（call_id=%s）", call.tool_name, call.call_id)
        return failure(
            broker,
            call,
            category=ErrorCategory.SERVER,
            message="工作区未就绪",
            suggestion="检查会话装配状态",
        )
    args: dict[str, object] = call.arguments
    timeout = descriptor.timeout_seconds or broker._settings.tool_default_timeout_seconds
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
        execution = await broker._script_executor.run(
            host_script=Path(descriptor.host_script_path),
            skill_dir=broker._skill_dir,
            workspace=broker._workspace,
            args=args,
            env_whitelist=broker._env_whitelist,
            timeout_seconds=timeout,
        )
    except PlatformError as exc:
        return failure_from_error(broker, call, descriptor, exc, start)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if execution.timed_out:
        logger.error(
            "脚本工具 %s 执行超时（%dms，call_id=%s）",
            call.tool_name,
            duration_ms,
            call.call_id,
        )
        return failure(
            broker,
            call,
            category=ErrorCategory.TIMEOUT,
            message="脚本执行超时",
            suggestion="缩小输入或分批",
            duration_ms=duration_ms,
        )
    if execution.exit_code != 0:
        message = script_failure_message(broker, execution)
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
        return failure(
            broker,
            call,
            category=ErrorCategory.SCRIPT,
            message=message,
            suggestion="检查输入参数或脚本输出",
            duration_ms=duration_ms,
        )
    content = execution.stdout or "（脚本无输出）"
    produced = [str(path.relative_to(broker._workspace)) for path in execution.produced_files]
    logger.debug(
        "脚本工具 %s 成功（%dms，stdout %d 字符，产物 %s，call_id=%s）",
        call.tool_name,
        duration_ms,
        len(execution.stdout),
        produced or "（无）",
        call.call_id,
    )
    result = await finish_success(broker, call, content, duration_ms)
    return result.model_copy(update={"produced_files": produced})


# ---- 结果构造 ----


def script_failure_message(broker: ToolBroker, execution: ScriptExecution) -> str:
    """脚本失败诊断：优先 stdout 错误载荷（契约规定失败信息走 stdout JSON），
    次选 stderr 尾部，最后回落退出码占位。截断至输出阈值防上下文撑爆。"""
    limit = broker._settings.tool_output_truncate_chars
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


async def finish_success(
    broker: ToolBroker, call: ToolCallRequest, content: str, duration_ms: int
) -> ToolResult:
    truncated_content, truncated = truncate_content(broker, content)
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        ok=True,
        content=truncated_content,
        duration_ms=duration_ms,
        truncated=truncated,
    )


def success(
    broker: ToolBroker, call: ToolCallRequest, content: str, duration_ms: int
) -> ToolResult:
    truncated_content, truncated = truncate_content(broker, content)
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        ok=True,
        content=truncated_content,
        duration_ms=duration_ms,
        truncated=truncated,
    )


def failure(
    broker: ToolBroker,
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


def failure_from_error(
    broker: ToolBroker,
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
    if descriptor.source == ToolSource.MCP and exc.category in _MCP_DEGRADE_CATEGORIES:
        broker._mark_server_degraded(descriptor.namespace)
    return failure(
        broker,
        call,
        category=exc.category,
        message=str(exc),
        suggestion=suggestion_for(broker, exc.category, descriptor.namespace),
        duration_ms=duration_ms,
    )


def not_found(broker: ToolBroker, call: ToolCallRequest) -> ToolResult:
    candidates = nearest(broker, call.tool_name)
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
        suggestion=f"相近候选：{', '.join(candidates)}" if candidates else "先用 search_tools 检索",
    )


def nearest(broker: ToolBroker, name: str, k: int = 3) -> list[str]:
    scored = sorted(broker._descriptors, key=lambda n: -_similarity(n, name))
    return [n for n in scored if n != name][:k]


def truncate_content(broker: ToolBroker, content: str) -> tuple[str, bool]:
    limit = broker._settings.tool_output_truncate_chars
    if len(content) <= limit:
        return content, False
    return truncate(content, max_length=limit), True


def suggestion_for(broker: ToolBroker, category: ErrorCategory, namespace: str) -> str:
    mapping: dict[ErrorCategory, str] = {
        ErrorCategory.TIMEOUT: "缩小输入或分批",
        ErrorCategory.RATE_LIMIT: "上游限流，稍后重试",
        ErrorCategory.AUTH: f"检查 {namespace or '服务'} 的令牌环境变量",
        ErrorCategory.BILLING: "数据源额度/套餐不可用，改用其他工具兜底并标注未检索到",
        ErrorCategory.CONNECTION: "服务连接失败，稍后重试",
        ErrorCategory.SERVER: "服务暂时不可用，走降级通道",
        ErrorCategory.INVALID_ARGUMENT: "按参数约束调整参数后重试",
        ErrorCategory.CONFIG: "检查服务配置",
    }
    return mapping.get(category, "重试或换用其他工具")
