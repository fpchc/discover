"""Run 持久化实现（P0 边界落地）。

- PostgreSQL：Run 快照（run_snapshots）与事件日志（run_events）为权威事实。
- Redis：短期租约 / 取消信号 / 执行者心跳。

本模块位于 application 层：它实现 harness.checkpoint 的协议，并组装
infrastructure 的具体客户端（Database / Redis）。不参与单回合业务判断。
"""

from __future__ import annotations

import json
from typing import Final

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness.checkpoint.protocol import EventLog, RunLease, SnapshotStore
from app.harness.events.run_events import RunEvent, run_event_adapter
from app.harness.execution.pipeline import PlannedAction, SideEffectClass
from app.harness.models import RunState
from app.infrastructure.database.base import local_now
from app.infrastructure.database.engine import Database
from app.infrastructure.database.models import RunActionRecord, RunEventRecord, RunSnapshotRecord

_RELEASE_SCRIPT: Final[str] = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class PostgresSnapshotStore(SnapshotStore):
    """Run 快照 PostgreSQL 实现。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def save(self, state: RunState) -> None:
        async with self._database.session_factory() as session:
            row = RunSnapshotRecord(
                run_id=state.identity.run_id,
                state_json=state.model_dump_json(),
                version=state.audit.version,
            )
            await session.merge(row)
            await session.commit()

    async def load(self, run_id: str) -> RunState | None:
        async with self._database.session_factory() as session:
            row = await session.get(RunSnapshotRecord, run_id)
        if row is None:
            return None
        return RunState.model_validate_json(row.state_json)

    async def delete(self, run_id: str) -> None:
        async with self._database.session_factory() as session:
            row = await session.get(RunSnapshotRecord, run_id)
            if row is not None:
                await session.delete(row)
                await session.commit()


class PostgresEventLog(EventLog):
    """Run 事件日志 PostgreSQL 实现（append-only）。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def append(self, event: RunEvent) -> int:
        payload = event.model_dump_json()
        async with self._database.session_factory() as session:
            seq = await self._next_seq(session, event.run_id)
            session.add(
                RunEventRecord(
                    run_id=event.run_id,
                    seq=seq,
                    event_type=event.type,
                    payload_json=payload,
                )
            )
            await session.commit()
        return seq

    async def events_after(self, run_id: str, seq: int) -> list[RunEvent]:
        async with self._database.session_factory() as session:
            result = await session.execute(
                select(RunEventRecord)
                .where(RunEventRecord.run_id == run_id, RunEventRecord.seq > seq)
                .order_by(RunEventRecord.seq)
            )
            rows = result.scalars().all()
        return [_to_event(row) for row in rows]

    async def last_seq(self, run_id: str) -> int:
        async with self._database.session_factory() as session:
            result = await session.execute(
                select(func.max(RunEventRecord.seq)).where(RunEventRecord.run_id == run_id)
            )
            value = result.scalar_one_or_none()
        return int(value) if value is not None else 0

    async def _next_seq(self, session: AsyncSession, run_id: str) -> int:
        result = await session.execute(
            select(func.max(RunEventRecord.seq)).where(RunEventRecord.run_id == run_id)
        )
        value = result.scalar_one_or_none()
        return int(value) + 1 if value is not None else 1


class RedisRunLease(RunLease):
    """Run 执行租约 Redis 实现。"""

    _LEASE_PREFIX = "run:lease:"
    _CANCEL_PREFIX = "run:cancel:"

    def __init__(
        self,
        client: aioredis.Redis,
        *,
        heartbeat_ttl_seconds: float = 60.0,
        cancel_ttl_seconds: int = 86400,
    ) -> None:
        self._client = client
        self._heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self._cancel_ttl_seconds = cancel_ttl_seconds
        self._release = client.register_script(_RELEASE_SCRIPT)

    def _lease_key(self, run_id: str) -> str:
        return f"{self._LEASE_PREFIX}{run_id}"

    def _cancel_key(self, run_id: str) -> str:
        return f"{self._CANCEL_PREFIX}{run_id}"

    async def acquire(self, run_id: str, *, owner_id: str, ttl_seconds: float) -> bool:
        acquired = await self._client.set(
            self._lease_key(run_id),
            owner_id,
            nx=True,
            px=int(ttl_seconds * 1000),
        )
        return bool(acquired)

    async def heartbeat(self, run_id: str, *, owner_id: str) -> bool:
        key = self._lease_key(run_id)
        current = await self._client.get(key)
        if current is None:
            return False
        current_text = current.decode("utf-8") if isinstance(current, bytes) else current
        if current_text != owner_id:
            return False
        await self._client.pexpire(key, int(self._heartbeat_ttl_seconds * 1000))
        return True

    async def release(self, run_id: str, *, owner_id: str) -> None:
        await self._release(keys=[self._lease_key(run_id)], args=[owner_id])

    async def cancel_requested(self, run_id: str) -> bool:
        return bool(await self._client.exists(self._cancel_key(run_id)))

    async def request_cancel(self, run_id: str, *, source: str) -> None:
        await self._client.set(
            self._cancel_key(run_id),
            source,
            ex=self._cancel_ttl_seconds,
        )


class PostgresActionCheckpoint:
    """副作用 Action 检查点 PostgreSQL 实现（planned → executed/failed）。

    供 ToolRuntime 的 CheckpointPort 使用：副作用工具执行前落 planned，执行后标记
    executed/failed；resume 时 load_pending 判「是否已发生」。
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    async def save_planned_action(self, planned: PlannedAction) -> None:
        async with self._database.session_factory() as session:
            session.add(
                RunActionRecord(
                    run_id=planned.run_id,
                    action_id=planned.action_id,
                    tool_name=planned.tool_name,
                    arguments_json=json.dumps(planned.arguments, ensure_ascii=False, default=str),
                    arguments_fingerprint=planned.arguments_fingerprint,
                    idempotency_key=planned.idempotency_key,
                    side_effect_class=planned.side_effect_class.value,
                    status="planned",
                    planned_at=planned.planned_at,
                )
            )
            await session.commit()

    async def mark_executed(self, run_id: str, action_id: str, *, ok: bool) -> None:
        async with self._database.session_factory() as session:
            result = await session.execute(
                select(RunActionRecord).where(
                    RunActionRecord.run_id == run_id,
                    RunActionRecord.action_id == action_id,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return
            row.status = "executed" if ok else "failed"
            row.executed_at = local_now()
            await session.commit()

    async def load_pending(self, run_id: str) -> list[PlannedAction]:
        async with self._database.session_factory() as session:
            result = await session.execute(
                select(RunActionRecord)
                .where(RunActionRecord.run_id == run_id, RunActionRecord.status == "planned")
                .order_by(RunActionRecord.id)
            )
            rows = result.scalars().all()
        return [_to_planned(row) for row in rows]


def _to_planned(row: RunActionRecord) -> PlannedAction:
    return PlannedAction(
        run_id=row.run_id,
        action_id=row.action_id,
        tool_name=row.tool_name,
        arguments=json.loads(row.arguments_json),
        arguments_fingerprint=row.arguments_fingerprint,
        idempotency_key=row.idempotency_key,
        side_effect_class=SideEffectClass(row.side_effect_class),
        planned_at=row.planned_at,
    )


def _to_event(row: RunEventRecord) -> RunEvent:
    event = run_event_adapter.validate_json(row.payload_json)
    return event.model_copy(update={"seq": row.seq})


__all__ = [
    "PostgresActionCheckpoint",
    "PostgresEventLog",
    "PostgresSnapshotStore",
    "RedisRunLease",
]
