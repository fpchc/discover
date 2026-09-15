"""模型候选结果验证器测试。"""

from __future__ import annotations

from app.harness.models import PhaseExecutionOutcome, PhaseExecutionOutcomeType
from app.harness.verification import (
    VerificationVerdict,
    verify_agent_outcome,
)


def _outcome(outcome_type: PhaseExecutionOutcomeType, **kwargs: object) -> PhaseExecutionOutcome:
    defaults: dict[str, object] = {"outcome_type": outcome_type, "reason_code": "t"}
    defaults.update(kwargs)
    return PhaseExecutionOutcome.model_validate(defaults)


def test_none_outcome_fails_verification() -> None:
    result = verify_agent_outcome(None)
    assert result.verdict == VerificationVerdict.FAIL


def test_input_required_is_not_success() -> None:
    outcome = _outcome(
        PhaseExecutionOutcomeType.INPUT_REQUIRED,
        answer="请补充时间范围",
        limitations=["range"],
    )
    result = verify_agent_outcome(outcome)
    assert result.verdict == VerificationVerdict.NEEDS_INPUT
    assert "range" in result.limitations


def test_final_proposed_with_answer_passes() -> None:
    outcome = _outcome(PhaseExecutionOutcomeType.FINAL_PROPOSED, answer="报告完成")
    result = verify_agent_outcome(outcome)
    assert result.verdict == VerificationVerdict.PASS


def test_candidate_completed_with_empty_payload_fails() -> None:
    outcome = _outcome(PhaseExecutionOutcomeType.CANDIDATE_COMPLETED, candidate_output=None)
    result = verify_agent_outcome(outcome)
    assert result.verdict == VerificationVerdict.FAIL


def test_candidate_completed_with_valid_schema_passes() -> None:
    outcome = _outcome(
        PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
        candidate_output={"title": "报告", "count": 3},
        output_schema={"required": ["title"], "properties": {"title": {"type": "string"}}},
    )
    result = verify_agent_outcome(outcome)
    assert result.verdict == VerificationVerdict.PASS


def test_candidate_completed_missing_required_field_fails() -> None:
    outcome = _outcome(
        PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
        candidate_output={},
        output_schema={"required": ["title"]},
    )
    result = verify_agent_outcome(outcome)
    assert result.verdict == VerificationVerdict.FAIL
    assert "title" in result.reason


def test_candidate_completed_type_mismatch_fails() -> None:
    outcome = _outcome(
        PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
        candidate_output={"count": "not-a-number"},
        output_schema={"properties": {"count": {"type": "integer"}}},
    )
    result = verify_agent_outcome(outcome)
    assert result.verdict == VerificationVerdict.FAIL
    assert "类型不符" in result.reason


def test_partial_budget_maps_to_partial() -> None:
    outcome = _outcome(PhaseExecutionOutcomeType.PARTIAL_BUDGET, answer="部分内容")
    result = verify_agent_outcome(outcome)
    assert result.verdict == VerificationVerdict.PARTIAL
