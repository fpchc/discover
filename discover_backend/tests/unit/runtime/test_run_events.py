"""Run 事件集测试（W1）：判别联合完整、终态事件契约、字段齐备。"""

from __future__ import annotations

import pytest
from app.runtime.events.run_events import (
    RunCancelled,
    RunCompleted,
    RunEvent,
    RunEventUnion,
    RunFailed,
    RunFinalizing,
    RunInputRequested,
    RunStarted,
    run_event_adapter,
)
from app.runtime.models import BudgetLimits, BudgetState, RunStatus, TerminationReason
from pydantic import TypeAdapter, ValidationError


def _budget() -> BudgetState:
    return BudgetState(
        limits=BudgetLimits(
            max_iterations=20,
            max_llm_calls=30,
            max_tool_calls=40,
            max_total_tokens=100000,
            max_input_tokens=80000,
            max_duration_seconds=300.0,
            max_repair_attempts=2,
            finalization_reserve_tokens=5000,
        )
    )


def test_run_event_adapter_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        run_event_adapter.validate_python({"type": "no_such_event"})


def test_run_event_discriminant_is_complete() -> None:
    """判别联合应覆盖全部事件类：跑一遍 adapter 归一。"""
    adapter: TypeAdapter[RunEventUnion] = run_event_adapter
    samples: list[RunEvent] = [
        RunStarted(type="run_started", run_id="r"),
        RunFinalizing(type="run_finalizing", run_id="r", reason=TerminationReason.NO_PROGRESS),
        RunFailed(type="run_failed", run_id="r"),
        RunCancelled(type="run_cancelled", run_id="r"),
        RunCompleted(
            type="run_completed",
            run_id="r",
            status="succeeded",
            termination_reason=TerminationReason.COMPLETED,
        ),
        RunInputRequested(type="run_input_requested", run_id="r", question="请补充"),
    ]
    for event in samples:
        restored = adapter.validate_json(event.model_dump_json())
        assert restored.type == event.type


def test_run_completed_partial_contract() -> None:
    """§17.1：PARTIAL 是正常完成类终态，不是 RunFailed，携带原因与未完成阶段。"""
    event = RunCompleted(
        type="run_completed",
        run_id="r1",
        step_id="s9",
        phase_id="p1",
        status="partial",
        termination_reason=TerminationReason.NO_PROGRESS,
        final_output="部分结果",
        completed_phases=["p1"],
        unfinished_phases=["p2"],
        limitations=["数据源不可用"],
        degraded_sources=["tencent_mcp"],
        budget_snapshot=_budget(),
    )
    restored = RunCompleted.model_validate_json(event.model_dump_json())
    assert restored.status == "partial"
    assert restored.termination_reason == TerminationReason.NO_PROGRESS
    assert restored.unfinished_phases == ["p2"]
    assert restored.limitations == ["数据源不可用"]
    assert restored.budget_snapshot is not None


def test_run_completed_status_restricted_to_terminal() -> None:
    """RunCompleted.status 只允许 succeeded / partial，不表达 failed。"""
    with pytest.raises(ValidationError):
        RunCompleted(
            type="run_completed",
            run_id="r",
            status="failed",  # type: ignore[arg-type]  # 测试非法终态
            termination_reason=TerminationReason.INTERNAL_ERROR,
        )


def test_run_cancelled_defaults_to_user_cancelled() -> None:
    event = RunCancelled(type="run_cancelled", run_id="r1")
    assert event.termination_reason == TerminationReason.USER_CANCELLED


def test_run_started_carries_run_identity() -> None:
    event = RunStarted(
        type="run_started",
        run_id="r1",
        account_id="acct",
        agent_id="agent-x",
        user_goal="查一下",
    )
    assert event.run_id == "r1"
    assert event.status == RunStatus.RUNNING
