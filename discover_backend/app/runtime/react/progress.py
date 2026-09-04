"""Action/Observation 指纹与无进展判定（react-runtime-v2-architecture §12）。

单一动机：识别「重复动作、重复结果、无进展循环」（§2.2-3）。指纹只判断
规范化后的结构是否相同，不能证明业务语义相同（§12.5 P1 近似性声明）。

判定逻辑（§12.4 六条件）：
  Action 指纹重复 + Observation 指纹重复 + 无新增证据 + 无新增产物
  + Contract 未改善 + 连续达到阈值 = no_progress
合法重试不误杀：上次为可重试错误、未超 max attempts、符合退避、Descriptor 允许。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping

from app.runtime.models import ProgressState
from app.shared.errors.base import ErrorCategory


def stable_dumps(value: object) -> str:
    """稳定序列化：sort_keys 递归排序嵌套 dict 键，保证指纹跨进程一致。

    不处理不可 JSON 序列化的值——参数是规范化 dict，超出即视为实现错误。
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def action_fingerprint(
    tool_name: str,
    arguments: Mapping[str, object],
    *,
    ignore_fields: Iterable[str] = (),
    phase_id: str = "",
) -> str:
    """Action 指纹（§12.2）：工具限定名 + 稳定规范化参数 JSON + 忽略字段 + 阶段 ID。

    动态时间戳、追踪 ID 等非语义字段由 Tool Descriptor 声明为不参与指纹。
    """
    ignored = frozenset(ignore_fields)
    filtered = {k: v for k, v in arguments.items() if k not in ignored}
    payload = f"{phase_id}|{tool_name}|{stable_dumps(filtered)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def observation_fingerprint(
    *,
    ok: bool,
    content_summary: str = "",
    error_category: ErrorCategory | None = None,
    artifact_summary: str = "",
    source: str = "",
) -> str:
    """Observation 指纹（§12.3）：成功/失败状态 + 归一化内容摘要 + 错误分类 + 产物摘要。

    内容摘要、截断和顺序变化可能影响 Observation 指纹（§12.5 近似性）。
    """
    payload = "|".join(
        [
            "ok" if ok else "fail",
            (error_category.value if error_category is not None else ""),
            source,
            content_summary.strip()[:2000],
            artifact_summary.strip()[:2000],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate_progress(
    progress: ProgressState,
    *,
    action_fp: str,
    observation_fp: str,
    new_evidence_count: int,
    new_artifact_count: int,
    contract_improved: bool,
    threshold: int,
) -> tuple[ProgressState, bool]:
    """评估一步迭代的进展（§12.4 六条件），返回（更新后状态, 是否命中 no_progress）。

    无进展 → consecutive_no_progress 累加；任一进展信号 → 清零。命中阈值时返回 True，
    由上层按 Policy 决策（默认 FINALIZE_PARTIAL，不是内部错误，§12.5）。
    """
    action_repeated = progress.last_action_fingerprint == action_fp
    observation_repeated = progress.last_observation_fingerprint == observation_fp
    made_progress = new_evidence_count > 0 or new_artifact_count > 0 or contract_improved
    consecutive = (
        progress.consecutive_no_progress + 1
        if (action_repeated and observation_repeated and not made_progress)
        else 0
    )
    updated = ProgressState(
        version=progress.version + 1,
        consecutive_no_progress=consecutive,
        last_action_fingerprint=action_fp,
        last_observation_fingerprint=observation_fp,
        new_evidence_count=new_evidence_count,
        new_artifact_count=new_artifact_count,
        contract_improved=contract_improved,
    )
    return updated, consecutive >= threshold
