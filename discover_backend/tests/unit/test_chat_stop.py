"""单元测试：stop 接口的取消链路。

覆盖设计评审中的关键风险点：
- 跨任务 task.cancel() 能真实中断承载 `_run_turn_events` 的任务（task 边界确认）；
- 预启动窗口（register 后、生成器未消费前）stop 仍生效；
- 归属校验 404 / idle / stopping 的响应语义。

纯本地：stub settings / fake runtime / fake history，无网络无 DB 无真实 Settings。
"""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace

import anyio
import pytest
from app.capabilities.llm.stream_parser import TextChunk
from app.interfaces.http.chat import _stream_sse, stop_chat_message
from app.interfaces.schemas import ChatStopResponse
from app.interfaces.schemas.conversations import ConversationSession, MessageStatus
from app.runtime.checkpoint.memory import (
    MemoryEventLog,
    MemoryRunLease,
    MemorySnapshotStore,
)
from app.runtime.service import RunService
from app.runtime.turn import ActiveTurn, ActiveTurnRegistry
from app.shared.errors.base import NotFoundError

_CONVERSATION_ID = "conv-stop-1"
_MESSAGE_ID = "msg-stop-1"
_CREATED_AT = 1700000000


class _FakeHistory:
    """伪历史服务：记录 record_turn 载荷，供断言。"""

    def __init__(self) -> None:
        self.turns: list[object] = []

    async def record_turn(self, conversation_id: str, turn: object) -> bool:
        self.turns.append(turn)
        return True

    async def get_history_messages(
        self, account_id: str, conversation_id: str, *, limit: int
    ) -> list[object]:
        return []


class _FakeLLMClient:
    """伪 LLM 客户端：产出部分正文后挂起，模拟进行中的 LLM 生成。"""

    async def stream_chat(
        self, *, provider: object, api_key: str, request: object
    ) -> AsyncIterator[TextChunk]:
        yield TextChunk(text="部分正文")
        await anyio.sleep_forever()


class _FakeProviders:
    """伪 Provider 注册表：resolve 返回占位 provider（假 client 不使用）。"""

    def resolve(self, provider_id: str) -> SimpleNamespace:
        return SimpleNamespace()


def _fake_settings() -> SimpleNamespace:
    """QueueEmitter 用到的 settings 字段（帧间隔 1ms 快速冲刷，避免时序依赖）。"""
    return SimpleNamespace(
        sse_queue_max_events=100,
        sse_heartbeat_interval_seconds=10,
        typewriter_frame_interval_ms=1,
        typewriter_chars_per_frame=100,
        typewriter_catchup_threshold=50,
        typewriter_catchup_ratio=4,
        thinking_frame_interval_ms=1,
        thinking_chars_per_frame=100,
        default_provider_id="test-provider",
        history_max_messages=50,
        error_message_max_chars=500,
        # _create_run 经 build_agent_budget 读取的预算字段
        agent_max_iterations=20,
        agent_max_llm_calls=30,
        agent_max_tool_calls=40,
        agent_max_total_tokens=100000,
        agent_max_input_tokens=80000,
        agent_max_duration_seconds=300.0,
        agent_max_repair_attempts=2,
        agent_finalization_reserve_tokens=5000,
        agent_context_summary_max_messages=10,
        agent_context_summary_max_chars=4000,
    )


def _services() -> SimpleNamespace:
    return SimpleNamespace(
        settings=_fake_settings(),
        conversation_service=_FakeHistory(),
        active_turns=ActiveTurnRegistry(),
        llm=_FakeLLMClient(),
        providers=_FakeProviders(),
        _resolve_api_key=lambda provider: "test-key",
        run_service=RunService(
            snapshots=MemorySnapshotStore(),
            events=MemoryEventLog(),
            lease=MemoryRunLease(),
            owner_id="test",
        ),
    )


def _session() -> ConversationSession:
    return ConversationSession(
        conversation_id=_CONVERSATION_ID,
        account_id="acct-1",
        assistant_target=None,
    )


# ---- stop 路由 handler 单测 ----


class _OwnedService:
    """require_owned spy：记录调用，不校验归属。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def require_owned(self, account_id: str, conversation_id: str) -> None:
        self.calls.append((account_id, conversation_id))


def _route_services() -> SimpleNamespace:
    return SimpleNamespace(
        conversation_service=_OwnedService(),
        active_turns=ActiveTurnRegistry(),
    )


async def test_stop_route_returns_stopping_with_message_id() -> None:
    services = _route_services()
    turn = ActiveTurn(message_id=_MESSAGE_ID)
    assert services.active_turns.register(_CONVERSATION_ID, turn) is True
    resp = await stop_chat_message(_CONVERSATION_ID, account_id="acct-1", services=services)
    assert isinstance(resp, ChatStopResponse)
    assert resp.status == "stopping"
    assert resp.message_id == _MESSAGE_ID
    assert services.conversation_service.calls == [("acct-1", _CONVERSATION_ID)]


async def test_stop_route_returns_idle_when_no_turn() -> None:
    services = _route_services()
    resp = await stop_chat_message(_CONVERSATION_ID, account_id="acct-1", services=services)
    assert isinstance(resp, ChatStopResponse)
    assert resp.status == "idle"
    assert resp.message_id is None


async def test_stop_route_propagates_not_owned_404() -> None:
    class _NotOwned:
        async def require_owned(self, account_id: str, conversation_id: str) -> None:
            raise NotFoundError(f"未知会话：{conversation_id}")

    services = SimpleNamespace(
        conversation_service=_NotOwned(),
        active_turns=ActiveTurnRegistry(),
    )
    with pytest.raises(NotFoundError):
        await stop_chat_message(_CONVERSATION_ID, account_id="acct-1", services=services)


# ---- 跨任务 stop 集成：真实 _run_turn_events ----


async def test_stop_cross_task_cancels_running_turn() -> None:
    """#1/#5 关键验证：stop 跨任务 task.cancel() 中断真实生成任务 → interrupted + partial。"""
    services = _services()
    turn = ActiveTurn(message_id=_MESSAGE_ID)
    assert services.active_turns.register(_CONVERSATION_ID, turn) is True
    frames: list[str] = []

    async def consume() -> None:
        async for frame in _stream_sse(
            services, "查询", _session(), _MESSAGE_ID, _CREATED_AT, turn
        ):
            frames.append(frame)

    task = asyncio.create_task(consume())
    # 等打字机冲刷出正文帧（帧间隔 1ms，50ms 绰绰有余）
    await anyio.sleep(0.05)
    assert frames, "应已产出部分正文帧"
    assert services.active_turns.get(_CONVERSATION_ID) is turn
    assert turn.task is task, "task 边界：捕获的必须是承载 _stream_sse 的业务任务"

    # 跨任务 stop：request_stop → task.cancel()（与客户端断连同原语）
    services.active_turns.request_stop(_CONVERSATION_ID)
    with anyio.fail_after(5):
        with pytest.raises(asyncio.CancelledError):
            await task
    assert task.cancelled()

    history = services.conversation_service
    assert isinstance(history, _FakeHistory)
    assert len(history.turns) == 1
    turn_record = history.turns[0]
    assert turn_record.status == MessageStatus.INTERRUPTED
    assert turn_record.answer == "部分正文"
    assert services.active_turns.get(_CONVERSATION_ID) is None


# ---- 预启动窗口 stop ----


async def test_stop_before_stream_start_persists_interrupted() -> None:
    """#2：register 后、生成器消费前 stop → 回合启动即中断 → interrupted 空 partial。"""
    services = _services()
    turn = ActiveTurn(message_id=_MESSAGE_ID)
    assert services.active_turns.register(_CONVERSATION_ID, turn) is True
    services.active_turns.request_stop(_CONVERSATION_ID)
    assert turn.task is None  # 未启动：只置标记，不调 cancel

    frames: list[str] = []
    with pytest.raises(asyncio.CancelledError):
        async for frame in _stream_sse(
            services, "查询", _session(), _MESSAGE_ID, _CREATED_AT, turn
        ):
            frames.append(frame)
    assert frames == []

    history = services.conversation_service
    assert isinstance(history, _FakeHistory)
    assert len(history.turns) == 1
    assert history.turns[0].status == MessageStatus.INTERRUPTED
    assert history.turns[0].answer is None
    assert services.active_turns.get(_CONVERSATION_ID) is None
