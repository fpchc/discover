"""Checkpoint 持久化：快照 / 事件日志 / 执行租约。

协议（protocol.py）定义持久化边界；memory.py 提供内存实现（测试与无 DB 默认）。
PostgreSQL/Redis 具体 store 在 bootstrap 接线阶段实现并替换（§16）。
"""

from app.runtime.checkpoint.memory import (
    MemoryEventLog,
    MemoryRunLease,
    MemorySnapshotStore,
)
from app.runtime.checkpoint.protocol import EventLog, RunLease, SnapshotStore

__all__ = [
    "EventLog",
    "MemoryEventLog",
    "MemoryRunLease",
    "MemorySnapshotStore",
    "RunLease",
    "SnapshotStore",
]
