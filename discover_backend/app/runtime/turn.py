"""进行中回合的注册与取消协调（stop 接口的服务器侧句柄）。

每次对话回合（streaming / blocking 共用入口）由路由层登记一个 ActiveTurn，
stop 路由据此取消对应会话的进行中回合；回合退出后注销。取消原语为
``asyncio.Task.cancel()`` —— 与 uvicorn 客户端断连同一机制，避免跨任务
CancelScope 取消「含嵌套任务组的任务」带来的死锁风险（见 emitter.py / container.py 注释）。

状态隔离：注册表挂在 AppServices 上，不设模块级全局态（CLAUDE.md §13.2）。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class ActiveTurn:
    """单回合的取消句柄（纯内部运行时句柄，不跨边界序列化）。

    task 在生成器 / blocking 首次执行时捕获真正承载回合的任务；
    stop_requested 覆盖「已注册但未启动」窗口的停止请求（幂等）。
    run_id 在回合启动时由 RunService.create 填充，stop 据此持久化 RunCancelled。
    """

    # pragma: 简化 — 纯内部可变句柄，非跨边界 DTO，无需 pydantic

    message_id: str
    run_id: str | None = None
    task: asyncio.Task[object] | None = None
    stop_requested: bool = False
    # 登记时刻（monotonic）：未启动句柄超时视为陈旧，由注册表自动回收（防泄漏锁）
    created_at: float = field(default_factory=time.monotonic)


class ActiveTurnRegistry:
    """会话 → 进行中回合句柄（单线程事件循环内 dict 操作天然原子）。

    register 在同会话已有句柄（含未启动）时拒绝，由路由转 409：底层 Runtime
    非并发安全（_emitter / _last_state 等共享可变态），并发回合会互相污染，
    故禁止而非静默覆盖。
    """

    def __init__(self, ttl_seconds: float = 120.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._turns: dict[str, ActiveTurn] = {}

    def register(self, conversation_id: str, turn: ActiveTurn) -> bool:
        """登记回合；同会话已有句柄 → False（不覆盖）。

        陈旧句柄（任务已结束 / 未启动超过 TTL）视为泄漏锁，直接覆盖而非 409：
        生成器未被消费/关闭时 unregister 不会执行，不回收会让会话永久卡死。
        """
        existing = self._turns.get(conversation_id)
        if existing is None:
            self._turns[conversation_id] = turn
            return True
        if self._is_stale(existing):
            self._turns[conversation_id] = turn
            return True
        return False

    def _is_stale(self, turn: ActiveTurn) -> bool:
        """进行中判定：任务已结束或未启动超过 TTL → 陈旧（可回收）。

        任务运行中永不视为陈旧（长回合安全）；未启动窗口（task 为 None）在
        TTL 内仍视为进行中（stop 预启动语义），超时才回收。
        """
        if turn.task is not None:
            return turn.task.done()
        return time.monotonic() - turn.created_at >= self._ttl_seconds

    def unregister(self, conversation_id: str, turn: ActiveTurn) -> None:
        """注销回合；身份比对，避免误删同会话的新句柄。"""
        if self._turns.get(conversation_id) is turn:
            del self._turns[conversation_id]

    def get(self, conversation_id: str) -> ActiveTurn | None:
        return self._turns.get(conversation_id)

    def request_stop(self, conversation_id: str) -> ActiveTurn | None:
        """请求停止：置标记并取消承载回合的任务；无回合返回 None。

        未启动（task 为 None）时只置标记，由回合启动处的检查兜底；
        已启动且未结束则 ``task.cancel()``。重复调用幂等（task.done() 后 cancel 是 no-op）。
        """
        turn = self._turns.get(conversation_id)
        if turn is None:
            return None
        turn.stop_requested = True
        if turn.task is not None and not turn.task.done():
            turn.task.cancel()
        return turn
