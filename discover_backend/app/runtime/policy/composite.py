"""组合 Policy（react-runtime-v2-architecture §11.1 composite）。

单一动机：把 budget / action / observation 各维度判定组合为单一 PolicyDecision。
组合规则：按严重度取最高（FAIL > TERMINATE > FINALIZE_PARTIAL > DEGRADE >
RETRY > SKIP > ALLOW），并列时优先保留不可恢复项。
"""

from __future__ import annotations

from app.runtime.policy.models import PolicyDecision, PolicyDecisionType

_SEVERITY: dict[PolicyDecisionType, int] = {
    PolicyDecisionType.ALLOW: 0,
    PolicyDecisionType.SKIP: 1,
    PolicyDecisionType.RETRY: 2,
    PolicyDecisionType.DEGRADE: 3,
    PolicyDecisionType.FINALIZE_PARTIAL: 4,
    PolicyDecisionType.TERMINATE: 5,
    PolicyDecisionType.FAIL: 6,
}


def compose(decisions: list[PolicyDecision]) -> PolicyDecision:
    """按严重度合并多个维度决策；空列表返回 ALLOW。"""
    if not decisions:
        return PolicyDecision(decision=PolicyDecisionType.ALLOW, reason_code="ok")
    return max(decisions, key=lambda decision: _severity(decision))


def _severity(decision: PolicyDecision) -> tuple[int, int]:
    base = _SEVERITY.get(decision.decision, 0)
    recoverable_bonus = 0 if decision.recoverable else 1
    return (base, recoverable_bonus)
