"""Action Policy（react-runtime-v2-architecture §11.1）。

单一动机：在工具执行前做确定性校验——工具是否存在且可用、参数 schema 是否通过、
是否越权使用其他阶段工具、是否为重复无进展动作、是否满足副作用/幂等要求。
Policy 只判定不执行工具（§21 职责边界）。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from app.capabilities.tools.descriptor import ToolDescriptor
from app.runtime.models import ActionRecord, ProgressState
from app.runtime.policy.models import PolicyDecision, PolicyDecisionType
from app.runtime.react.progress import action_fingerprint


def check_action(
    *,
    descriptor: ToolDescriptor | None,
    arguments: Mapping[str, object],
    allowed_tools: Iterable[str],
    recent_actions: Iterable[ActionRecord],
    progress: ProgressState,
    progress_threshold: int,
) -> PolicyDecision:
    """Action 执行前判定（§11.1 Action Policy / §12.4 无进展）。

    判定顺序：存在性 → 阶段白名单 → schema 校验 → 重复无进展。
    ALLOW 才允许进入执行管线；RETRY/DEGRADE/TERMINATE 由上层据此分支。
    """
    if descriptor is None:
        return PolicyDecision(
            decision=PolicyDecisionType.TERMINATE,
            reason_code="tool_not_found",
            display_message="请求的工具不在目录中",
            recoverable=False,
        )
    qualified = descriptor.qualified_name
    allowed = frozenset(allowed_tools)
    if allowed and qualified not in allowed:
        return PolicyDecision(
            decision=PolicyDecisionType.DEGRADE,
            reason_code="tool_not_allowed_in_phase",
            display_message=f"工具 {qualified} 不在当前阶段白名单",
            recoverable=True,
        )
    schema_error = _validate_schema(descriptor, arguments)
    if schema_error is not None:
        return PolicyDecision(
            decision=PolicyDecisionType.RETRY,
            reason_code="invalid_tool_arguments",
            display_message=schema_error,
            recoverable=True,
        )
    if _is_repeated_no_progress(qualified, arguments, recent_actions, progress, progress_threshold):
        return PolicyDecision(
            decision=PolicyDecisionType.FINALIZE_PARTIAL,
            reason_code="repeated_action_no_progress",
            display_message="重复动作且无进展，停止工具探索",
            recoverable=True,
        )
    return PolicyDecision(decision=PolicyDecisionType.ALLOW, reason_code="ok")


def _validate_schema(descriptor: ToolDescriptor, arguments: Mapping[str, object]) -> str | None:
    """按 descriptor.parameters（JSON Schema 子集）校验必填字段与类型。

    首期为必填字段存在性 + string/number/integer/boolean 基础类型检查；
    完整 JSON Schema 校验由 Tool Runtime 在 schema 验证节扩展（§15 管线）。
    """
    required = _required_fields(descriptor.parameters)
    missing = [field for field in required if field not in arguments]
    if missing:
        return f"缺少必填参数：{', '.join(missing)}"
    for field, value in arguments.items():
        if not _type_matches(descriptor.parameters, field, value):
            return f"参数 {field} 类型不符"
    return None


def _required_fields(parameters: Mapping[str, object]) -> list[str]:
    raw = parameters.get("required")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    return []


def _type_matches(parameters: Mapping[str, object], field: str, value: object) -> bool:
    props = parameters.get("properties")
    if not isinstance(props, Mapping):
        return True
    field_schema = props.get(field)
    if not isinstance(field_schema, Mapping):
        return True
    declared = field_schema.get("type")
    if not isinstance(declared, str):
        return True
    if value is None:
        return True
    if declared == "string":
        return isinstance(value, str)
    if declared == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared == "boolean":
        return isinstance(value, bool)
    return True


def _is_repeated_no_progress(
    tool_name: str,
    arguments: Mapping[str, object],
    recent_actions: Iterable[ActionRecord],
    progress: ProgressState,
    threshold: int,
) -> bool:
    """重复动作 + 无进展判定（§12.4）：action 指纹在最近动作中出现，且已连续无进展。

    指纹忽略字段由 Tool Descriptor 声明，这里不感知；仅用 ActionRecord 已有的
    arguments_fingerprint（§8.4）。合法重试不误杀由上层依据 Descriptor.retryable 判断。
    """
    candidate = action_fingerprint(tool_name, arguments)
    repeated = any(record.arguments_fingerprint == candidate for record in recent_actions)
    return repeated and progress.consecutive_no_progress >= threshold


def fingerprint_json(arguments: Mapping[str, object]) -> str:
    """参数规范化为指纹（工具内稳定 JSON，供 ActionRecord 复用）。"""
    return json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
