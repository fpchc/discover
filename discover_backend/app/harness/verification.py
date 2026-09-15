"""模型候选结果验证器（P0 边界：候选 ≠ 完成）。

单一动机：把「模型提交候选结果」与「系统验证成立」拆开。终态只能由
Verifier 决定，不能由 outcome 类型直接映射为 succeeded。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.harness.contracts.structural import structural_failures
from app.harness.models import (
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
)


class VerificationVerdict(StrEnum):
    """验证结论：PASS / NEEDS_INPUT / PARTIAL / FAIL。"""

    PASS = "pass"
    NEEDS_INPUT = "needs_input"
    PARTIAL = "partial"
    FAIL = "fail"


class OutcomeVerification(BaseModel):
    """一次验证结果。"""

    verdict: VerificationVerdict
    reason: str = ""
    limitations: list[str] = Field(default_factory=list)


def verify_agent_outcome(
    outcome: PhaseExecutionOutcome | None,
) -> OutcomeVerification:
    """候选结果验证（当前采用结构化确定性判定）。"""
    if outcome is None:
        return OutcomeVerification(
            verdict=VerificationVerdict.FAIL,
            reason="模型未产出可验证结果",
        )
    if outcome.outcome_type == PhaseExecutionOutcomeType.INPUT_REQUIRED:
        return OutcomeVerification(
            verdict=VerificationVerdict.NEEDS_INPUT,
            reason="需要用户补充输入",
            limitations=outcome.limitations,
        )
    if outcome.outcome_type == PhaseExecutionOutcomeType.FINAL_PROPOSED:
        if outcome.answer:
            return OutcomeVerification(
                verdict=VerificationVerdict.PASS,
                reason="最终答案非空，通过验证",
                limitations=outcome.limitations,
            )
        return OutcomeVerification(
            verdict=VerificationVerdict.FAIL,
            reason="最终答案为空，未通过验证",
            limitations=outcome.limitations,
        )
    if outcome.outcome_type == PhaseExecutionOutcomeType.CANDIDATE_COMPLETED:
        failures = structural_failures(outcome.output_schema, outcome.candidate_output)
        if failures:
            return OutcomeVerification(
                verdict=VerificationVerdict.FAIL,
                reason="候选输出未通过结构契约：" + "；".join(failures),
                limitations=outcome.limitations,
            )
        if _has_candidate_payload(outcome):
            return OutcomeVerification(
                verdict=VerificationVerdict.PASS,
                reason="候选输出通过结构契约",
                limitations=outcome.limitations,
            )
        return OutcomeVerification(
            verdict=VerificationVerdict.FAIL,
            reason="候选输出为空，未通过验证",
            limitations=outcome.limitations,
        )
    if outcome.outcome_type == PhaseExecutionOutcomeType.PARTIAL_NO_PROGRESS:
        return OutcomeVerification(
            verdict=VerificationVerdict.PARTIAL,
            reason="无进展，部分完成",
            limitations=outcome.limitations or ["无进展，部分完成"],
        )
    if outcome.outcome_type == PhaseExecutionOutcomeType.PARTIAL_BUDGET:
        return OutcomeVerification(
            verdict=VerificationVerdict.PARTIAL,
            reason="预算受限，部分完成",
            limitations=outcome.limitations or ["预算受限，部分完成"],
        )
    return OutcomeVerification(
        verdict=VerificationVerdict.FAIL,
        reason="Contract 或阶段结果未通过验证",
        limitations=outcome.limitations,
    )


def _has_candidate_payload(outcome: PhaseExecutionOutcome) -> bool:
    """候选载荷是否可交付（终态至少要有 answer 或 candidate_output）。"""
    if outcome.answer:
        return True
    return outcome.candidate_output is not None and bool(outcome.candidate_output)


__all__ = [
    "OutcomeVerification",
    "VerificationVerdict",
    "verify_agent_outcome",
]
