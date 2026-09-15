"""Run Service 测试（W6-W7）：create/resume/cancel/query + checkpoint 契约。

使用内存 store（MemorySnapshotStore / MemoryEventLog / MemoryRunLease），
不触数据库（CLAUDE.md §9）。验证：进程可恢复快照、同一 Run 不被并发推进、
取消请求与终态事件、SSE 重连查询。
"""

from __future__ import annotations

import pytest
from app.harness.checkpoint.memory import (
    MemoryEventLog,
    MemoryRunLease,
    MemorySnapshotStore,
)
from app.harness.events.run_events import RunCancelled, RunInputRequested, RunStarted
from app.harness.models import (
    BudgetLimits,
    BudgetState,
    RunStatus,
    TerminationReason,
)
from app.harness.service import RunService


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


def _service(
    *, owner_id: str = "owner-1", lease_ttl_seconds: float = 120.0
) -> tuple[RunService, MemorySnapshotStore, MemoryEventLog, MemoryRunLease]:
    snapshots = MemorySnapshotStore()
    events = MemoryEventLog()
    lease = MemoryRunLease()
    service = RunService(
        snapshots=snapshots,
        events=events,
        lease=lease,
        owner_id=owner_id,
        lease_ttl_seconds=lease_ttl_seconds,
    )
    return service, snapshots, events, lease


async def test_create_persists_snapshot_and_start_event() -> None:
    service, snapshots, events, _lease = _service()
    state = await service.create(
        conversation_id="conv-1",
        message_id="msg-1",
        account_id="acct-1",
        agent_id="agent-x",
        skill_id="skill-y",
        user_goal="查一下",
        budget=_budget(),
        phases=["p1"],
    )
    assert state.identity.run_id
    assert state.termination.status == RunStatus.CREATED
    # 快照可恢复
    restored = await snapshots.load(state.identity.run_id)
    assert restored is not None
    assert restored.goal.agent_id == "agent-x"
    # 事件日志含 RunStarted
    tail = await events.events_after(state.identity.run_id, 0)
    assert any(isinstance(e, RunStarted) for e in tail)


async def test_complete_persists_final_output_in_snapshot() -> None:
    service, snapshots, _events, _lease = _service()
    state = await service.create(
        conversation_id="conv-1",
        message_id="msg-1",
        account_id="acct-1",
        agent_id="agent-x",
        skill_id=None,
        user_goal="查一下",
        budget=_budget(),
        phases=["p1"],
    )
    await service.complete(
        state.identity.run_id,
        status="succeeded",
        reason=TerminationReason.COMPLETED,
        final_output="最终答案",
    )
    restored = await snapshots.load(state.identity.run_id)
    assert restored is not None
    assert restored.output.final_draft == "最终答案"


async def test_resume_restores_state() -> None:
    service, _snapshots, _events, lease = _service()
    state = await service.create(
        conversation_id="conv-1",
        message_id="msg-1",
        account_id="acct-1",
        agent_id="agent-x",
        skill_id=None,
        user_goal="目标",
        budget=_budget(),
        phases=["p1"],
    )
    # create 已持有租约；模拟执行者崩溃后租约过期/释放，再恢复
    await lease.release(state.identity.run_id, owner_id="owner-1")
    resumed = await service.resume(state.identity.run_id)
    assert resumed is not None
    assert resumed.identity.run_id == state.identity.run_id


async def test_resume_unknown_run_returns_none() -> None:
    service, _snapshots, _events, _lease = _service()
    assert await service.resume("no-such-run") is None


async def test_second_owner_cannot_resume_active_run() -> None:
    """§16.4：同一 Run 同时只能有一个执行者（共享同一租约存储）。"""
    snapshots = MemorySnapshotStore()
    events = MemoryEventLog()
    lease = MemoryRunLease()
    owner_service = RunService(
        snapshots=snapshots,
        events=events,
        lease=lease,
        owner_id="owner-1",
    )
    other_service = RunService(
        snapshots=snapshots,
        events=events,
        lease=lease,
        owner_id="owner-2",
    )
    state = await owner_service.create(
        conversation_id="conv-1",
        message_id="msg-1",
        account_id="acct-1",
        agent_id="agent-x",
        skill_id=None,
        user_goal="目标",
        budget=_budget(),
        phases=["p1"],
    )
    # owner-1 已持有租约（create 时 acquire），owner-2 不能恢复
    assert await other_service.resume(state.identity.run_id) is None


async def test_cancel_requests_flag_and_cancelled_event() -> None:
    service, snapshots, events, lease = _service()
    state = await service.create(
        conversation_id="conv-1",
        message_id="msg-1",
        account_id="acct-1",
        agent_id="agent-x",
        skill_id=None,
        user_goal="目标",
        budget=_budget(),
        phases=["p1"],
    )
    run_id = state.identity.run_id
    ok = await service.cancel(run_id, source="user")
    assert ok is True
    assert await lease.cancel_requested(run_id) is True
    tail = await events.events_after(run_id, 0)
    assert any(isinstance(e, RunCancelled) for e in tail)
    # 快照 cancellation 已标记
    restored = await snapshots.load(run_id)
    assert restored is not None
    assert restored.control.cancellation.requested is True


async def test_cancel_unknown_run_returns_false() -> None:
    service, _snapshots, _events, _lease = _service()
    assert await service.cancel("no-such-run", source="user") is False


async def test_resume_after_cancel_marks_cancelled_terminal() -> None:
    service, _snapshots, _events, lease = _service()
    state = await service.create(
        conversation_id="conv-1",
        message_id="msg-1",
        account_id="acct-1",
        agent_id="agent-x",
        skill_id=None,
        user_goal="目标",
        budget=_budget(),
        phases=["p1"],
    )
    run_id = state.identity.run_id
    # 释放租约后重新获取（模拟执行者重启）
    await lease.release(run_id, owner_id="owner-1")
    await service.cancel(run_id, source="user")
    resumed = await service.resume(run_id)
    assert resumed is not None
    assert resumed.termination.status == RunStatus.CANCELLED
    assert resumed.termination.reason == TerminationReason.USER_CANCELLED


async def test_wait_for_input_releases_lease_and_persists_state() -> None:
    """需要用户输入时：快照 WAITING_INPUT + RunInputRequested 事件 + 释放租约。"""
    service, snapshots, events, _lease = _service()
    state = await service.create(
        conversation_id="conv-1",
        message_id="msg-1",
        account_id="acct-1",
        agent_id="agent-x",
        skill_id="skill-y",
        user_goal="查一下",
        budget=_budget(),
        phases=["p1"],
    )
    run_id = state.identity.run_id
    assert (
        await service.wait_for_input(run_id, question="请补充时间范围", missing_fields=["range"])
        is True
    )
    restored = await snapshots.load(run_id)
    assert restored is not None
    assert restored.termination.status == RunStatus.WAITING_INPUT
    assert restored.output.final_draft == "请补充时间范围"
    tail = await events.events_after(run_id, 0)
    assert any(isinstance(e, RunInputRequested) for e in tail)
    # 租约已释放：同 owner 可以重新 resume（不再被占用）
    resumed = await service.resume(run_id)
    assert resumed is not None


async def test_query_returns_snapshot_and_events_after_seq() -> None:
    service, _snapshots, _events, _lease = _service()
    state = await service.create(
        conversation_id="conv-1",
        message_id="msg-1",
        account_id="acct-1",
        agent_id="agent-x",
        skill_id=None,
        user_goal="目标",
        budget=_budget(),
        phases=["p1"],
    )
    run_id = state.identity.run_id
    result = await service.query(run_id, after_seq=0)
    assert result is not None
    assert result.state.identity.run_id == run_id
    assert any(isinstance(e, RunStarted) for e in result.events)
    # SSE 重连：after_seq 过滤
    result_after = await service.query(run_id, after_seq=result.last_seq)
    assert result_after is not None
    assert result_after.events == []


async def test_query_unknown_run_returns_none() -> None:
    service, _snapshots, _events, _lease = _service()
    assert await service.query("no-such-run") is None


async def test_pending_actions_empty_when_checkpoint_absent() -> None:
    service, _snapshots, _events, _lease = _service()
    assert await service.pending_actions("r1") == []


async def test_pending_actions_reports_unfinished_side_effects() -> None:
    from app.harness.execution.pipeline import PlannedAction, SideEffectClass

    class _FakeCheckpoint:
        async def load_pending(self, run_id: str) -> list[PlannedAction]:
            del run_id
            return [
                PlannedAction(
                    run_id="r1",
                    action_id="p1.1.c1",
                    tool_name="send_email",
                    arguments={"to": "a@b.c"},
                    arguments_fingerprint="fp",
                    idempotency_key="k1",
                    side_effect_class=SideEffectClass.EXTERNAL_WRITE,
                )
            ]

        async def save_planned_action(self, planned: PlannedAction) -> None:
            del planned

        async def mark_executed(self, run_id: str, action_id: str, *, ok: bool) -> None:
            del run_id, action_id, ok

    service = RunService(
        snapshots=MemorySnapshotStore(),
        events=MemoryEventLog(),
        lease=MemoryRunLease(),
        owner_id="owner-1",
        action_checkpoint=_FakeCheckpoint(),
    )
    pending = await service.pending_actions("r1")
    assert len(pending) == 1
    assert pending[0].tool_name == "send_email"


def test_service_requires_injected_dependencies() -> None:
    with pytest.raises(TypeError):
        RunService()  # type: ignore[call-arg]  # 缺必填注入
