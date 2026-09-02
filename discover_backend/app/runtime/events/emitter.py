"""会话级事件发射器：seq 分配、打字机节流、心跳、有界队列背压。

对话输出只能走 SSE。本类是运行时节点与 SSE 写循环之间的唯一通道；
写循环消费 get()，客户端断开时取消 run()，资源随任务组释放。
"""

import asyncio
import logging
from collections import deque
from collections.abc import Callable

import anyio

from app.config.settings import Settings
from app.runtime.events.events import (
    AgentEvent,
    HeartbeatEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
)
from app.shared.utils.graphemes import split_graphemes

logger = logging.getLogger(__name__)


class _BoundedEventQueue:
    """有界事件队列，实现 sse-streaming-spec §7 背压与丢弃策略。

    - 增量事件（正文/思考）可合并：队尾为同类型增量时直接并入，不新增条目；
    - 心跳可丢弃：队列满直接丢弃；
    - 关键事件（工具调用/产物/错误/完成）不可丢弃不可合并：满则背压等待。
    """

    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._items: deque[AgentEvent] = deque()
        self._lock = asyncio.Lock()
        self._can_get = asyncio.Condition(self._lock)
        self._can_put = asyncio.Condition(self._lock)

    async def put(self, event: AgentEvent) -> None:
        async with self._lock:
            while True:
                if self._merge_tail(event):
                    return
                if len(self._items) < self._maxsize:
                    self._items.append(event)
                    self._can_get.notify()
                    return
                if isinstance(event, HeartbeatEvent):
                    return
                await self._can_put.wait()

    async def get(self) -> AgentEvent:
        async with self._lock:
            while not self._items:
                await self._can_get.wait()
            event = self._items.popleft()
            self._can_put.notify()
            return event

    def _merge_tail(self, event: AgentEvent) -> bool:
        if not self._items:
            return False
        tail = self._items[-1]
        if isinstance(event, TextDeltaEvent) and isinstance(tail, TextDeltaEvent):
            tail.text += event.text
            return True
        if isinstance(event, ThinkingDeltaEvent) and isinstance(tail, ThinkingDeltaEvent):
            tail.text += event.text
            return True
        return False


class _TypewriterChannel:
    """单通道打字机：缓冲 + 帧切分 + 追赶提速。"""

    def __init__(
        self,
        *,
        frame_interval: float,
        chars_per_frame: int,
        catchup_threshold: int,
        catchup_ratio: int,
        delta_factory: Callable[[str], TextDeltaEvent | ThinkingDeltaEvent],
    ) -> None:
        self._frame_interval = frame_interval
        self._chars_per_frame = chars_per_frame
        self._catchup_threshold = catchup_threshold
        self._catchup_ratio = catchup_ratio
        self._delta_factory = delta_factory
        self._buffer: deque[str] = deque()
        self._speed_up = False

    @property
    def frame_interval(self) -> float:
        return self._frame_interval

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def mark_speed_up(self) -> None:
        self._speed_up = True

    def append(self, text: str) -> None:
        self._buffer.extend(split_graphemes(text))

    def _frame_size(self) -> int:
        size = self._chars_per_frame
        if self._speed_up or self.pending > self._catchup_threshold:
            size *= self._catchup_ratio
        return size

    def take(self, *, force_all: bool) -> str:
        size = self.pending if force_all else self._frame_size()
        parts: list[str] = []
        for _ in range(size):
            if not self._buffer:
                break
            parts.append(self._buffer.popleft())
        return "".join(parts)

    def next_event(self, *, force_all: bool) -> AgentEvent | None:
        text = self.take(force_all=force_all)
        if not text:
            return None
        return self._delta_factory(text)


class QueueEmitter:
    """会话级事件发射器。seq 由本类统一分配，保证单调递增。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._queue = _BoundedEventQueue(settings.sse_queue_max_events)
        self._seq = 0
        self._text = _TypewriterChannel(
            frame_interval=settings.typewriter_frame_interval_ms / 1000.0,
            chars_per_frame=settings.typewriter_chars_per_frame,
            catchup_threshold=settings.typewriter_catchup_threshold,
            catchup_ratio=settings.typewriter_catchup_ratio,
            delta_factory=lambda chunk: TextDeltaEvent(text=chunk),
        )
        self._thinking = _TypewriterChannel(
            frame_interval=settings.thinking_frame_interval_ms / 1000.0,
            chars_per_frame=settings.thinking_chars_per_frame,
            catchup_threshold=settings.typewriter_catchup_threshold,
            catchup_ratio=settings.typewriter_catchup_ratio,
            delta_factory=lambda chunk: ThinkingDeltaEvent(text=chunk),
        )

    def text_delta(self, text: str) -> None:
        """追加正文增量（同步入缓冲，由帧任务节流推送）。"""
        self._text.append(text)

    def thinking_delta(self, text: str) -> None:
        """追加思考增量（同步入缓冲，独立节流参数推送）。"""
        self._thinking.append(text)

    async def emit(self, event: AgentEvent) -> None:
        """发射非增量事件（路由/工具/产物/错误/完成等）。"""
        if isinstance(event, (TextDeltaEvent, ThinkingDeltaEvent, HeartbeatEvent)):
            raise TypeError("增量与心跳事件应走专用方法")
        await self._flush_pending_frames()
        await self._stamp_and_put(event)

    async def finish(self) -> None:
        """模型结束：以帧粒度快速冲刷剩余文本（提速但不一次性倒完）。"""
        self._text.mark_speed_up()
        self._thinking.mark_speed_up()
        await self._flush_pending_frames()

    async def get(self) -> AgentEvent:
        """供 SSE 写循环消费下一个事件。"""
        return await self._queue.get()

    async def run(self) -> None:
        """驱动打字机与心跳循环；随会话流生命周期运行，取消即停。

        单协程轮询，不做嵌套任务组：本机 anyio/asyncio 组合下，父作用域取消
        含嵌套任务组的子任务会死锁（SSE 流尾挂起），单协程在 sleep 处即可
        干净取消，各通道仍按自身节拍推进。
        """
        text_interval = self._text.frame_interval
        thinking_interval = self._thinking.frame_interval
        heartbeat_interval = self._settings.sse_heartbeat_interval_seconds
        next_text = anyio.current_time() + text_interval
        next_thinking = anyio.current_time() + thinking_interval
        next_heartbeat = anyio.current_time() + heartbeat_interval
        try:
            while True:
                next_tick = min(next_text, next_thinking, next_heartbeat)
                await anyio.sleep(max(0.0, next_tick - anyio.current_time()))
                now = anyio.current_time()
                if now >= next_text:
                    await self._tick(self._text)
                    next_text += text_interval
                if now >= next_thinking:
                    await self._tick(self._thinking)
                    next_thinking += thinking_interval
                if now >= next_heartbeat:
                    await self._stamp_and_put(HeartbeatEvent())
                    next_heartbeat += heartbeat_interval
        finally:
            logger.info(
                "emitter.run 退出",
                extra={
                    "seq": self._seq,
                    "text_pending": self._text.pending,
                    "thinking_pending": self._thinking.pending,
                },
            )

    async def _flush_pending_frames(self) -> None:
        for channel in (self._text, self._thinking):
            while channel.pending:
                event = channel.next_event(force_all=False)
                if event is None:
                    break
                await self._stamp_and_put(event)

    async def _stamp_and_put(self, event: AgentEvent) -> None:
        await self._queue.put(self._stamp(event))

    def _stamp(self, event: AgentEvent) -> AgentEvent:
        self._seq += 1
        return event.model_copy(update={"seq": self._seq})

    async def _tick(self, channel: _TypewriterChannel) -> None:
        """单次节拍：从通道取一帧，非空则入队。"""
        event = channel.next_event(force_all=False)
        if event is not None:
            await self._stamp_and_put(event)
