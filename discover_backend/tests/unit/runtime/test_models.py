"""状态模型测试（W1）：序列化往返、枚举穷尽、指纹字段齐备、P0-2 接缝契约。"""

from __future__ import annotations

import pytest
from app.runtime.models import (
    ActionRecord,
    BudgetLimits,
    BudgetState,
    CancellationState,
    ObservationRecord,
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
    PhaseOutput,
    PhaseState,
    ProgressState,
    RunControl,
    RunGoal,
    RunIdentity,
    RunState,
    RunStatus,
    TerminationReason,
)
from app.shared.errors.base import ErrorCategory
from pydantic import ValidationError


def _limits(**overrides: object) -> BudgetLimits:
    base: dict[str, object] = {
        "max_iterations": 20,
        "max_llm_calls": 30,
        "max_tool_calls": 40,
        "max_total_tokens": 100000,
        "max_input_tokens": 80000,
        "max_duration_seconds": 300.0,
        "max_repair_attempts": 2,
        "finalization_reserve_tokens": 5000,
    }
    base.update(overrides)
    return BudgetLimits(**base)


def _run_state(**overrides: object) -> RunState:
    budget = BudgetState(limits=_limits())
    base = RunState(
        identity=RunIdentity(
            run_id="run-1",
            conversation_id="conv-1",
            message_id="msg-1",
            account_id="acct-1",
        ),
        goal=RunGoal(agent_id="agent-x", skill_id="skill-y", user_goal="查一下"),
        workflow={
            "phase_ids": ["p1"],
            "current_phase_id": "p1",
            "phases": {"p1": PhaseState(phase_id="p1")},
        },
        control=RunControl(budget=budget),
    )
    return base.model_copy(update=overrides)


# ---- 枚举穷尽 ----
def test_termination_reason_has_twelve_kinds() -> None:
    expected = {
        "completed",
        "iteration_limit",
        "token_budget",
        "time_budget",
        "tool_budget",
        "no_progress",
        "contract_failed",
        "required_tool_unavailable",
        "user_cancelled",
        "client_disconnected",
        "runtime_shutdown",
        "internal_error",
    }
    assert {reason.value for reason in TerminationReason} == expected


def test_run_status_terminal_set() -> None:
    terminal = {
        RunStatus.SUCCEEDED,
        RunStatus.PARTIAL,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
    non_terminal = set(RunStatus) - terminal
    assert non_terminal == {
        RunStatus.CREATED,
        RunStatus.RUNNING,
        RunStatus.WAITING_INPUT,
        RunStatus.RECOVERING,
        RunStatus.CANCEL_REQUESTED,
        RunStatus.FINALIZING,
    }


# ---- RunState 序列化 / 反序列化 ----
def test_run_state_round_trip_preserves_identity() -> None:
    state = _run_state()
    restored = RunState.model_validate_json(state.model_dump_json())
    assert restored.identity.run_id == "run-1"
    assert restored.goal.agent_id == "agent-x"
    assert restored.control.budget.limits.max_iterations == 20


def test_run_state_defaults_partial_false() -> None:
    state = _run_state()
    assert state.termination.partial is False
    assert state.termination.status == RunStatus.CREATED


def test_run_state_requires_identity_and_budget() -> None:
    with pytest.raises(ValidationError):
        RunState()  # type: ignore[call-arg]  # 测试构造缺字段


# ---- 指纹字段齐备（§8.4）----
def test_action_record_has_fingerprint_fields() -> None:
    record = ActionRecord(
        action_id="a1",
        step_id="s1",
        tool_name="tool.x",
        arguments={"q": "a"},
        arguments_fingerprint="fp",
        idempotency_key="idem-1",
        status="proposed",
    )
    assert record.arguments_fingerprint == "fp"
    assert record.idempotency_key == "idem-1"
    restored = ActionRecord.model_validate_json(record.model_dump_json())
    assert restored.tool_name == "tool.x"


def test_observation_record_has_fingerprint_and_error() -> None:
    record = ObservationRecord(
        observation_id="o1",
        step_id="s1",
        action_id="a1",
        status="failed",
        observation_fingerprint="ofp",
        error_category=ErrorCategory.SERVER,
        truncated=True,
        progress_delta=0,
    )
    assert record.observation_fingerprint == "ofp"
    assert record.error_category == ErrorCategory.SERVER
    restored = ObservationRecord.model_validate_json(record.model_dump_json())
    assert restored.truncated is True


# ---- 控制状态 ----
def test_budget_soft_hard_lists() -> None:
    budget = BudgetState(limits=_limits(), soft_exceeded=["iterations"], hard_exceeded=["duration"])
    assert budget.soft_exceeded == ["iterations"]
    assert budget.hard_exceeded == ["duration"]


def test_progress_cancellation_defaults() -> None:
    assert ProgressState().consecutive_no_progress == 0
    cancellation = CancellationState()
    assert cancellation.requested is False


# ---- P0-2 接缝契约（§9.4）----
def test_phase_execution_request_round_trip() -> None:
    request = PhaseExecutionRequest(
        run_id="run-1",
        phase_instance_id="p1",
        phase_goal="完成查询",
        allowed_tools=["tool.a"],
        budget=BudgetState(limits=_limits()),
    )
    restored = PhaseExecutionRequest.model_validate_json(request.model_dump_json())
    assert restored.phase_goal == "完成查询"
    assert restored.allowed_tools == ["tool.a"]


def test_phase_execution_outcome_all_types() -> None:
    for outcome_type in PhaseExecutionOutcomeType:
        outcome = PhaseExecutionOutcome(outcome_type=outcome_type)
        restored = PhaseExecutionOutcome.model_validate_json(outcome.model_dump_json())
        assert restored.outcome_type == outcome_type


def test_phase_output_is_versioned() -> None:
    output = PhaseOutput(
        phase_id="p1",
        data={"score": 0.8},
        evidence_refs=["e1"],
        limitations=["来源不足"],
    )
    assert output.schema_version == 1
    restored = PhaseOutput.model_validate_json(output.model_dump_json())
    assert restored.data["score"] == 0.8
