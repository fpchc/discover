"""预算 Policy 单元测试：软/硬边界 + Finalization Reserve 预留区。

覆盖 check_budget 的四种路径：未触限 ALLOW、触软限 FINALIZE_PARTIAL、
进入预留区 FINALIZE_PARTIAL（软）、触硬限 TERMINATE。
"""

from __future__ import annotations

from app.runtime.models import BudgetKind, BudgetLimits, BudgetState, BudgetUsage
from app.runtime.policy.budget import check_budget
from app.runtime.policy.models import PolicyDecisionType


def _budget(
    *,
    total_tokens: int = 0,
    input_tokens: int = 0,
    max_total_tokens: int = 100000,
    max_input_tokens: int = 80000,
    reserve: int = 5000,
) -> BudgetState:
    return BudgetState(
        limits=BudgetLimits(
            max_iterations=20,
            max_llm_calls=30,
            max_tool_calls=40,
            max_total_tokens=max_total_tokens,
            max_input_tokens=max_input_tokens,
            max_duration_seconds=300.0,
            max_repair_attempts=2,
            finalization_reserve_tokens=reserve,
        ),
        usage=BudgetUsage(total_tokens=total_tokens, input_tokens=input_tokens),
    )


def test_check_budget_allows_below_limits() -> None:
    decision = check_budget(_budget(total_tokens=90000, input_tokens=70000))
    assert decision.decision == PolicyDecisionType.ALLOW


def test_check_budget_entering_reserve_triggers_partial() -> None:
    """进预留区（>= limit - reserve）→ FINALIZE_PARTIAL，不再硬性终止。"""
    decision = check_budget(_budget(total_tokens=96000))
    assert decision.decision == PolicyDecisionType.FINALIZE_PARTIAL
    assert decision.budget_snapshot is not None
    assert BudgetKind.TOTAL_TOKENS in decision.budget_snapshot.soft_exceeded


def test_check_budget_input_tokens_reserve_triggers_partial() -> None:
    decision = check_budget(_budget(input_tokens=76000))
    assert decision.decision == PolicyDecisionType.FINALIZE_PARTIAL
    assert decision.budget_snapshot is not None
    assert BudgetKind.INPUT_TOKENS in decision.budget_snapshot.soft_exceeded


def test_check_budget_hard_limit_still_terminates() -> None:
    """触达硬上限仍确定性终止，reserve 不撤销硬边界。"""
    decision = check_budget(_budget(total_tokens=100000))
    assert decision.decision == PolicyDecisionType.TERMINATE
    assert decision.budget_snapshot is not None
    assert BudgetKind.TOTAL_TOKENS in decision.budget_snapshot.hard_exceeded


def test_check_budget_zero_reserve_disables_softening() -> None:
    """reserve=0 时预留区不生效，低位用量保持 ALLOW。"""
    decision = check_budget(_budget(total_tokens=96000, reserve=0))
    assert decision.decision == PolicyDecisionType.ALLOW
