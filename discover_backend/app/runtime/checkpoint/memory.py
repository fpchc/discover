"""内存 Checkpoint store（测试与无 DB 默认运行）。

单一动机：提供 SnapshotStore / EventLog / RunLease 的内存实现，满足
checkpoint.protocol 契约。PostgreSQL/Redis 具体实现在 bootstrap 接线阶段
替换本类（W6-W7 落地 store 时）；Service 只依赖协议，不感知存储后端。
内存态不跨进程共享（§16.4 明确不得依赖进程内全局字典实现跨进程唯一执行）。
"""

from __future__ import annotations

import time

from app.runtime.checkpoint.protocol import EventLog, RunLease, SnapshotStore
from app.runtime.events.run_events import RunEvent
from app.runtime.models import RunState


class MemorySnapshotStore(SnapshotStore):
    """内存 Run 快照存储。"""

    def __init__(self) -> None:
        self._snapshots: dict[str, RunState] = {}

    async def save(self, state: RunState) -> None:
        self._snapshots[state.identity.run_id] = state.model_copy(deep=True)

    async def load(self, run_id: str) -> RunState | None:
        state = self._snapshots.get(run_id)
        return state.model_copy(deep=True) if state is not None else None

    async def delete(self, run_id: str) -> None:
        self._snapshots.pop(run_id, None)


class MemoryEventLog(EventLog):
    """内存 Append-only 事件日志（进程内；跨进程审计需换持久化实现）。"""

    def __init__(self) -> None:
        self._events: dict[str, list[RunEvent]] = {}

    async def append(self, event: RunEvent) -> None:
        seq = await self.last_seq(event.run_id) + 1
        stored = event.model_copy(update={"seq": seq})
        self._events.setdefault(event.run_id, []).append(stored)

    async def events_after(self, run_id: str, seq: int) -> list[RunEvent]:
        events = self._events.get(run_id, [])
        return [event for event in events if event.seq > seq]

    async def last_seq(self, run_id: str) -> int:
        events = self._events.get(run_id, [])
        return events[-1].seq if events else 0


class MemoryRunLease(RunLease):
    """内存执行租约（单进程内保证唯一执行者；跨进程需 Redis 实现）。"""

    def __init__(self) -> None:
        self._leases: dict[str, tuple[str, float]] = {}
        self._cancel_flags: dict[str, str] = {}

    async def acquire(self, run_id: str, *, owner_id: str, ttl_seconds: float) -> bool:
        current = self._leases.get(run_id)
        now = time.monotonic()
        if current is None or current[1] < now:
            self._leases[run_id] = (owner_id, now + ttl_seconds)
            return True
        return False

    async def heartbeat(self, run_id: str, *, owner_id: str) -> bool:
        current = self._leases.get(run_id)
        if current is None or current[0] != owner_id:
            return False
        self._leases[run_id] = (owner_id, time.monotonic() + 60.0)
        return True

    async def release(self, run_id: str, *, owner_id: str) -> None:
        current = self._leases.get(run_id)
        if current is not None and current[0] == owner_id:
            self._leases.pop(run_id, None)

    async def cancel_requested(self, run_id: str) -> bool:
        return run_id in self._cancel_flags

    async def request_cancel(self, run_id: str, *, source: str) -> None:
        self._cancel_flags[run_id] = source
