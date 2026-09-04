"""Run Service（react-runtime-v2-architecture §16 / §17 接口适配）。

单一动机：Run 生命周期的服务入口——create / resume / cancel / complete / fail / query。
只依赖 checkpoint 协议（SnapshotStore / EventLog / RunLease），不感知存储后端
（DIP，CLAUDE.md §6）。执行与事件订阅解耦：HTTP/SSE 负责映射，Service 不感知
LangGraph 内部节点（§21 职责边界）。

断连与取消分离（§17.3）：SSE 断开仅停止订阅；显式 cancel 才请求取消 Run。
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.runtime.checkpoint.protocol import EventLog, RunLease, SnapshotStore
from app.runtime.events.run_events import (
    RunCancelled,
    RunCompleted,
    RunEvent,
    RunFailed,
    RunStarted,
)
from app.runtime.models import (
    BudgetState,
    CancellationState,
    RunAudit,
    RunContext,
    RunControl,
    RunGoal,
    RunIdentity,
    RunOutput,
    RunState,
    RunStatus,
    RunTermination,
    RunWorkflow,
    TerminationReason,
)
from app.shared.errors.base import ErrorCategory


class RunQueryResult(BaseModel):
    """查询结果（跨边界 DTO）：Run 快照 + 指定 seq 之后的事件（SSE 重连用）。"""

    state: RunState
    events: list[RunEvent] = Field(default_factory=list)
    last_seq: int = 0


class RunService:
    """Run 生命周期服务（create/resume/cancel/query）。"""

    def __init__(
        self,
        *,
        snapshots: SnapshotStore,
        events: EventLog,
        lease: RunLease,
        owner_id: str,
        lease_ttl_seconds: float = 120.0,
    ) -> None:
        self._snapshots = snapshots
        self._events = events
        self._lease = lease
        self._owner_id = owner_id
        self._lease_ttl_seconds = lease_ttl_seconds

    async def create(
        self,
        *,
        conversation_id: str,
        message_id: str,
        account_id: str,
        agent_id: str,
        skill_id: str | None,
        user_goal: str,
        budget: BudgetState,
        phases: list[str],
    ) -> RunState:
        """创建 Run：初始化状态 + 落库快照 + 事件日志 + 获取执行租约。"""
        run_id = uuid.uuid4().hex
        state = RunState(
            identity=RunIdentity(
                run_id=run_id,
                conversation_id=conversation_id,
                message_id=message_id,
                account_id=account_id,
            ),
            goal=RunGoal(agent_id=agent_id, skill_id=skill_id, user_goal=user_goal),
            workflow=RunWorkflow(phase_ids=phases, current_phase_id=phases[0] if phases else None),
            context=RunContext(),
            output=RunOutput(),
            control=RunControl(budget=budget),
            audit=RunAudit(version=1),
            termination=RunTermination(),
        )
        await self._snapshots.save(state)
        await self._events.append(
            RunStarted(
                run_id=run_id,
                account_id=account_id,
                agent_id=agent_id,
                skill_id=skill_id,
                user_goal=user_goal,
            )
        )
        await self._lease.acquire(
            run_id, owner_id=self._owner_id, ttl_seconds=self._lease_ttl_seconds
        )
        return state

    async def resume(self, run_id: str) -> RunState | None:
        """恢复 Run：读取快照 + 重新获取租约。租约被占用返回 None。"""
        state = await self._snapshots.load(run_id)
        if state is None:
            return None
        acquired = await self._lease.acquire(
            run_id, owner_id=self._owner_id, ttl_seconds=self._lease_ttl_seconds
        )
        if not acquired:
            return None
        if await self._lease.cancel_requested(run_id):
            state.termination.status = RunStatus.CANCELLED
            state.termination.reason = TerminationReason.USER_CANCELLED
            await self._snapshots.save(state)
        return state

    async def cancel(self, run_id: str, *, source: str) -> bool:
        """请求取消 Run（§17.3：显式 cancel 才取消，SSE 断连不触发）。"""
        state = await self._snapshots.load(run_id)
        if state is None:
            return False
        await self._lease.request_cancel(run_id, source=source)
        state.control.cancellation = CancellationState(requested=True, source=source)
        await self._snapshots.save(state)
        await self._events.append(RunCancelled(run_id=run_id, message=source))
        return True

    async def complete(
        self,
        run_id: str,
        *,
        status: Literal["succeeded", "partial"],
        reason: TerminationReason,
        final_output: str = "",
        completed_phases: list[str] | None = None,
        unfinished_phases: list[str] | None = None,
        limitations: list[str] | None = None,
    ) -> bool:
        """正常完成类终态（§17.1）：更新快照 termination + 追加 RunCompleted 事件。"""
        state = await self._snapshots.load(run_id)
        if state is None:
            return False
        state.termination.status = (
            RunStatus.SUCCEEDED if status == "succeeded" else RunStatus.PARTIAL
        )
        state.termination.reason = reason
        state.termination.partial = status == "partial"
        await self._snapshots.save(state)
        await self._events.append(
            RunCompleted(
                run_id=run_id,
                status=status,
                termination_reason=reason,
                final_output=final_output,
                completed_phases=completed_phases or [],
                unfinished_phases=unfinished_phases or [],
                limitations=limitations or [],
            )
        )
        return True

    async def fail(
        self,
        run_id: str,
        *,
        reason: TerminationReason = TerminationReason.INTERNAL_ERROR,
        message: str = "",
        error_category: ErrorCategory | None = None,
    ) -> bool:
        """失败终态（§17.1）：更新快照 termination + 追加 RunFailed 事件。"""
        state = await self._snapshots.load(run_id)
        if state is None:
            return False
        state.termination.status = RunStatus.FAILED
        state.termination.reason = reason
        state.termination.error_message = message
        state.termination.error_category = error_category
        await self._snapshots.save(state)
        await self._events.append(
            RunFailed(
                run_id=run_id,
                termination_reason=reason,
                error_category=error_category,
                message=message,
            )
        )
        return True

    async def query(self, run_id: str, *, after_seq: int = 0) -> RunQueryResult | None:
        """查询 Run：快照 + after_seq 之后的事件（SSE 重连订阅）。"""
        state = await self._snapshots.load(run_id)
        if state is None:
            return None
        events = await self._events.events_after(run_id, after_seq)
        last_seq = await self._events.last_seq(run_id)
        return RunQueryResult(state=state, events=events, last_seq=last_seq)
