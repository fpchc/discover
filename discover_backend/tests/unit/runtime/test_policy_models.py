"""Policy 决策模型测试（W1）：七种结构化枚举穷尽 + 字段齐备 + 序列化。"""

from __future__ import annotations

import pytest
from app.runtime.policy.models import PolicyDecision, PolicyDecisionType
from pydantic import ValidationError


def test_policy_decision_types_exhaustive() -> None:
    assert {t.value for t in PolicyDecisionType} == {
        "allow",
        "retry",
        "skip",
        "degrade",
        "finalize_partial",
        "terminate",
        "fail",
    }


def test_policy_decision_fields() -> None:
    decision = PolicyDecision(
        decision=PolicyDecisionType.RETRY,
        reason_code="tool_temporary_error",
        display_message="工具暂时不可用，正在重试",
        retry_delay_seconds=1.5,
        attempt=2,
        fallback_phase="p2",
        recoverable=True,
    )
    assert decision.decision == PolicyDecisionType.RETRY
    assert decision.reason_code == "tool_temporary_error"
    assert decision.retry_delay_seconds == 1.5


def test_policy_decision_round_trip() -> None:
    decision = PolicyDecision(decision=PolicyDecisionType.TERMINATE, recoverable=False)
    restored = PolicyDecision.model_validate_json(decision.model_dump_json())
    assert restored.decision == PolicyDecisionType.TERMINATE
    assert restored.recoverable is False


def test_policy_decision_requires_type() -> None:
    with pytest.raises(ValidationError):
        PolicyDecision()  # type: ignore[call-arg]  # 测试缺必填字段


def test_policy_decision_defaults() -> None:
    decision = PolicyDecision(decision=PolicyDecisionType.ALLOW)
    assert decision.reason_code == ""
    assert decision.recoverable is True
    assert decision.budget_snapshot is None
