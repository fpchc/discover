"""Action/Observation 指纹与无进展判定测试（W2，§12）。"""

from __future__ import annotations

from app.runtime.models import ProgressState
from app.runtime.react.progress import (
    action_fingerprint,
    evaluate_progress,
    observation_fingerprint,
    stable_dumps,
)
from app.shared.errors.base import ErrorCategory


# ---- 指纹 ----
def test_stable_dumps_sorts_nested_keys() -> None:
    assert stable_dumps({"b": 1, "a": {"d": 2, "c": 3}}) == '{"a":{"c":3,"d":2},"b":1}'


def test_action_fingerprint_stable_order() -> None:
    left = action_fingerprint("tool.x", {"b": 1, "a": 2})
    right = action_fingerprint("tool.x", {"a": 2, "b": 1})
    assert left == right


def test_action_fingerprint_ignores_declared_fields() -> None:
    with_stamp = action_fingerprint(
        "tool.x", {"q": "a", "trace_id": "t1"}, ignore_fields=["trace_id"]
    )
    without_stamp = action_fingerprint(
        "tool.x", {"q": "a", "trace_id": "t2"}, ignore_fields=["trace_id"]
    )
    assert with_stamp == without_stamp


def test_action_fingerprint_phase_id_scoped() -> None:
    in_p1 = action_fingerprint("tool.x", {"q": "a"}, phase_id="p1")
    in_p2 = action_fingerprint("tool.x", {"q": "a"}, phase_id="p2")
    assert in_p1 != in_p2


def test_observation_fingerprint_distinguishes_error() -> None:
    ok = observation_fingerprint(ok=True, content_summary="结果")
    failed = observation_fingerprint(
        ok=False, content_summary="结果", error_category=ErrorCategory.SERVER
    )
    assert ok != failed


# ---- 无进展判定（§12.4 六条件）----
def _progress(**overrides: int) -> ProgressState:
    base = ProgressState()
    return base.model_copy(update=overrides)


def test_repeated_action_and_observation_hits_threshold() -> None:
    state = _progress()
    # 首次调用建立基线（last_fingerprint=None 不判重复）
    state, stalled = evaluate_progress(
        state,
        action_fp="A",
        observation_fp="O",
        new_evidence_count=0,
        new_artifact_count=0,
        contract_improved=False,
        threshold=3,
    )
    assert stalled is False
    # 连续重复达到阈值 → no_progress
    for _ in range(3):
        state, stalled = evaluate_progress(
            state,
            action_fp="A",
            observation_fp="O",
            new_evidence_count=0,
            new_artifact_count=0,
            contract_improved=False,
            threshold=3,
        )
    assert stalled is True
    assert state.consecutive_no_progress == 3


def test_new_evidence_resets_no_progress() -> None:
    state = _progress()
    state, _ = evaluate_progress(
        state,
        action_fp="A",
        observation_fp="O",
        new_evidence_count=0,
        new_artifact_count=0,
        contract_improved=False,
        threshold=5,
    )
    state, stalled = evaluate_progress(
        state,
        action_fp="A",
        observation_fp="O",
        new_evidence_count=1,  # 新增证据 → 有进展
        new_artifact_count=0,
        contract_improved=False,
        threshold=5,
    )
    assert stalled is False
    assert state.consecutive_no_progress == 0


def test_same_action_new_observation_allows_continue() -> None:
    """§23.1：相同 Action 但 Observation 指纹变化 → 不判定无进展，可继续。"""
    state = _progress()
    state, stalled = evaluate_progress(
        state,
        action_fp="A",
        observation_fp="O1",
        new_evidence_count=0,
        new_artifact_count=0,
        contract_improved=False,
        threshold=3,
    )
    assert stalled is False
    # 同一 Action，Observation 变成 O2（指纹不同）→ 不累计无进展
    state, stalled = evaluate_progress(
        state,
        action_fp="A",
        observation_fp="O2",
        new_evidence_count=0,
        new_artifact_count=0,
        contract_improved=False,
        threshold=3,
    )
    assert stalled is False
    assert state.consecutive_no_progress == 0


def test_contract_improvement_counts_as_progress() -> None:
    state = _progress()
    state, stalled = evaluate_progress(
        state,
        action_fp="A",
        observation_fp="O",
        new_evidence_count=0,
        new_artifact_count=0,
        contract_improved=True,
        threshold=3,
    )
    assert stalled is False
    assert state.consecutive_no_progress == 0


def test_below_threshold_not_stalled() -> None:
    state = _progress()
    state, _ = evaluate_progress(
        state,
        action_fp="A",
        observation_fp="O",
        new_evidence_count=0,
        new_artifact_count=0,
        contract_improved=False,
        threshold=5,
    )
    # 第二次重复累计 1，仍低于阈值 → 不判定
    state, stalled = evaluate_progress(
        state,
        action_fp="A",
        observation_fp="O",
        new_evidence_count=0,
        new_artifact_count=0,
        contract_improved=False,
        threshold=5,
    )
    assert stalled is False
    assert state.consecutive_no_progress == 1
