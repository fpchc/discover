"""Run Service 测试（W6-W7）：create/resume/cancel/query + checkpoint 契约。

使用内存 store（MemorySnapshotStore / MemoryEventLog / MemoryRunLease），
不触数据库（CLAUDE.md §9）。验证：进程可恢复快照、同一 Run 不被并发推进、
取消请求与终态事件、SSE 重连查询。
"""

from __future__ import annotations

import pytest
from app.runtime.checkpoint.memory import (
    MemoryEventLog,
    MemoryRunLease,
    MemorySnapshotStore,
)
from app.runtime.events.run_events import RunCancelled, RunStarted
from app.runtime.models import (
    BudgetLimits,
    BudgetState,
    RunStatus,
    TerminationReason,
)
from app.runtime.service import RunService


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


def test_service_requires_injected_dependencies() -> None:
    with pytest.raises(TypeError):
        RunService()  # type: ignore[call-arg]  # 缺必填注入
