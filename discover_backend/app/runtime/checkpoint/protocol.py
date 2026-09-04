"""Checkpoint 持久化协议（react-runtime-v2-architecture §16）。

单一动机：定义 Run 快照与事件日志的持久化边界。活跃 Run 内存态为权威，
只在阶段边界与副作用边界持久化（§16.1）；PostgreSQL/Redis 具体实现由
bootstrap 接线（W6-W7 落地 store 时实现），本协议保证 Service 只依赖抽象。
"""

from __future__ import annotations

from typing import Protocol

from app.runtime.events.run_events import RunEvent
from app.runtime.models import RunState


class SnapshotStore(Protocol):
    """Run 快照存储：阶段/副作用边界落库，进程重启后恢复。"""

    async def save(self, state: RunState) -> None: ...
    async def load(self, run_id: str) -> RunState | None: ...
    async def delete(self, run_id: str) -> None: ...


class EventLog(Protocol):
    """Append-only 事件日志：audit + 重连订阅（§16.1 durable audit）。"""

    async def append(self, event: RunEvent) -> None: ...
    async def events_after(self, run_id: str, seq: int) -> list[RunEvent]: ...
    async def last_seq(self, run_id: str) -> int: ...


class RunLease(Protocol):
    """执行租约（§16.4）：同一 Run 同时只能有一个执行者。

    PostgreSQL 状态版本 + Redis 租约（owner/lease/heartbeat/乐观版本/cancel flag）。
    """

    async def acquire(self, run_id: str, *, owner_id: str, ttl_seconds: float) -> bool: ...
    async def heartbeat(self, run_id: str, *, owner_id: str) -> bool: ...
    async def release(self, run_id: str, *, owner_id: str) -> None: ...
    async def cancel_requested(self, run_id: str) -> bool: ...
    async def request_cancel(self, run_id: str, *, source: str) -> None: ...
