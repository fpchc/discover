"""预算 Policy（react-runtime-v2-architecture §10.2 / §13）。

单一动机：把 BudgetState 的用量与限额比对为软/硬边界判定。Soft → 停止工具探索
进入部分总结；Hard → 禁止任何新 LLM/工具调用，确定性终止（§10.2），绝不追加
「请总结」system message 后直接结束。

哪些维度算 Hard 由 hard_kinds 注入（默认保守：迭代/时长/token/修复次数），
具体数值上限来自配置与 Skill 声明（CLAUDE.md §5，不硬编码）。
"""

from __future__ import annotations

from collections.abc import Iterable

from app.runtime.models import BudgetKind, BudgetState
from app.runtime.policy.models import PolicyDecision, PolicyDecisionType

# 默认按「可恢复性」划分：资源耗竭/时间/修复次数为硬性；调用次数为软性（可转总结）。
_DEFAULT_HARD_KINDS: frozenset[BudgetKind] = frozenset(
    {
        BudgetKind.ITERATIONS,
        BudgetKind.DURATION,
        BudgetKind.TOTAL_TOKENS,
        BudgetKind.REPAIR_ATTEMPTS,
    }
)


def check_budget(
    budget: BudgetState,
    *,
    hard_kinds: Iterable[BudgetKind] = (),
    max_hard_violations: int = 0,
) -> PolicyDecision:
    """比对用量与限额，返回 ALLOW / FINALIZE_PARTIAL（软）/ TERMINATE（硬）。

    返回 ALLOW 时不改动 budget；软/硬超限时在 decision 上挂 budget_snapshot，
    由上层决定是否写入状态。soft 命中 → FINALIZE_PARTIAL，hard 命中 → TERMINATE。
    """
    hard = frozenset(hard_kinds) or _DEFAULT_HARD_KINDS
    soft_kinds: list[BudgetKind] = []
    hard_kinds_hit: list[BudgetKind] = []
    for kind in BudgetKind:
        used = _used_for(budget, kind)
        limit = _limit_for(budget, kind)
        if limit is None or used is None:
            continue
        if used >= limit:
            if kind in hard:
                hard_kinds_hit.append(kind)
            else:
                soft_kinds.append(kind)
    budget_snapshot = budget.model_copy(
        update={"soft_exceeded": soft_kinds, "hard_exceeded": hard_kinds_hit}
    )
    if hard_kinds_hit:
        return PolicyDecision(
            decision=PolicyDecisionType.TERMINATE,
            reason_code=f"hard_budget:{','.join(k.value for k in hard_kinds_hit)}",
            display_message="已达硬性预算上限，确定性终止",
            budget_snapshot=budget_snapshot,
            recoverable=False,
        )
    if soft_kinds:
        return PolicyDecision(
            decision=PolicyDecisionType.FINALIZE_PARTIAL,
            reason_code=f"soft_budget:{','.join(k.value for k in soft_kinds)}",
            display_message="预算接近上限，停止工具探索并汇总部分结果",
            budget_snapshot=budget_snapshot,
            recoverable=True,
        )
    return PolicyDecision(decision=PolicyDecisionType.ALLOW, budget_snapshot=budget_snapshot)


def _used_for(budget: BudgetState, kind: BudgetKind) -> int | float | None:
    usage = budget.usage
    if kind == BudgetKind.ITERATIONS:
        return usage.iterations
    if kind == BudgetKind.LLM_CALLS:
        return usage.llm_calls
    if kind == BudgetKind.TOOL_CALLS:
        return usage.tool_calls
    if kind == BudgetKind.TOTAL_TOKENS:
        return usage.total_tokens
    if kind == BudgetKind.INPUT_TOKENS:
        return usage.input_tokens
    if kind == BudgetKind.DURATION:
        return usage.duration_seconds
    if kind == BudgetKind.REPAIR_ATTEMPTS:
        return usage.repair_attempts
    return None


def _limit_for(budget: BudgetState, kind: BudgetKind) -> int | float | None:
    limits = budget.limits
    if kind == BudgetKind.ITERATIONS:
        return limits.max_iterations
    if kind == BudgetKind.LLM_CALLS:
        return limits.max_llm_calls
    if kind == BudgetKind.TOOL_CALLS:
        return limits.max_tool_calls
    if kind == BudgetKind.TOTAL_TOKENS:
        return limits.max_total_tokens
    if kind == BudgetKind.INPUT_TOKENS:
        return limits.max_input_tokens
    if kind == BudgetKind.DURATION:
        return limits.max_duration_seconds
    if kind == BudgetKind.REPAIR_ATTEMPTS:
        return limits.max_repair_attempts
    return None
