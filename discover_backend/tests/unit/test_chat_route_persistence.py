"""单元测试：chat-messages 路由层的两段式落库与并发锁语义。

覆盖：用户提问先 start_turn 落 processing 记录（仅 query）→ 回合结束
record_turn 更新 thinking/answer；streaming 下 message_end 后锁已释放；
同会话真实运行中仍 409 且不落 processing 记录。纯本地：伪事件源 + 伪历史，
无网络无 DB。
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from app.interfaces.http.chat import chat_messages
from app.interfaces.schemas import ChatMessageRequest
from app.interfaces.schemas.conversations import (
    ConversationSession,
    MessageStatus,
    TurnRecord,
    TurnStartRecord,
)
from app.runtime.events.run_events import RunCompleted, RunEvent, TextDelta, ThinkingDelta
from app.runtime.models import TerminationReason
from app.runtime.turn import ActiveTurn, ActiveTurnRegistry
from app.shared.errors.base import ConflictError
from fastapi import Response

_CONVERSATION_ID = "conv-route-1"


class _FakeHistory:
    """伪历史服务：记录 start_turn / record_turn 载荷，供断言两段式落库。"""

    def __init__(self) -> None:
        self.starts: list[TurnStartRecord] = []
        self.turns: list[TurnRecord] = []

    async def resolve(
        self,
        *,
        account_id: str,
        conversation_id: str,
        agent_id: str,
        query: str,
    ) -> ConversationSession:
        del conversation_id, agent_id, query
        return ConversationSession(
            conversation_id=_CONVERSATION_ID,
            account_id=account_id,
            assistant_target=None,
        )

    async def start_turn(self, conversation_id: str, start: TurnStartRecord) -> None:
        del conversation_id
        self.starts.append(start)

    async def record_turn(self, conversation_id: str, turn: TurnRecord) -> bool:
        del conversation_id
        self.turns.append(turn)
        return True


async def _fake_events_normal(
    services: object,
    session: object,
    user_input: str,
    *,
    turn: object,
) -> AsyncIterator[RunEvent]:
    del services, session, user_input, turn
    yield TextDelta(text="正文A")
    yield ThinkingDelta(text="思考B")
    yield RunCompleted(
        status="succeeded",
        termination_reason=TerminationReason.COMPLETED,
    )


async def _spin_forever() -> None:
    await asyncio.sleep(3600)


def _services() -> tuple[SimpleNamespace, _FakeHistory, ActiveTurnRegistry]:
    history = _FakeHistory()
    registry = ActiveTurnRegistry()
    services = SimpleNamespace(conversation_service=history, active_turns=registry)
    return services, history, registry


async def test_blocking_persists_start_then_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """blocking：路由先落 processing（query），回合结束更新 thinking/answer，锁释放。"""
    monkeypatch.setattr("app.interfaces.http.chat._run_turn_events", _fake_events_normal)
    services, history, registry = _services()
    resp = await chat_messages(
        ChatMessageRequest(query="你好", response_mode="blocking"),
        Response(),
        account_id="acct-1",
        services=services,
    )
    # 两段式：先 start（processing 仅 query），后 record（终态 + thinking/answer）
    assert len(history.starts) == 1
    start = history.starts[0]
    assert start.message_id == resp.message_id
    assert start.query == "你好"
    assert start.status is MessageStatus.PROCESSING
    assert start.account_id == "acct-1"
    assert len(history.turns) == 1
    turn = history.turns[0]
    assert turn.answer == "正文A"
    assert turn.thinking == "思考B"
    assert turn.status is MessageStatus.NORMAL
    assert registry.get(_CONVERSATION_ID) is None


async def test_streaming_start_turn_at_route_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """streaming：路由层（响应体消费前）即落 processing 记录；流结束后锁释放。"""
    monkeypatch.setattr("app.interfaces.http.chat._run_turn_events", _fake_events_normal)
    services, history, registry = _services()
    resp = await chat_messages(
        ChatMessageRequest(query="你好", response_mode="streaming"),
        Response(),
        account_id="acct-1",
        services=services,
    )
    assert len(history.starts) == 1
    assert history.starts[0].query == "你好"
    assert history.starts[0].status is MessageStatus.PROCESSING
    assert registry.get(_CONVERSATION_ID) is not None  # 流未消费：仍登记进行中
    frames: list[str] = []
    async for frame in resp.body_iterator:
        frames.append(frame)
    assert len(history.turns) == 1
    assert history.turns[0].answer == "正文A"
    assert registry.get(_CONVERSATION_ID) is None
    assert any("message_end" in frame for frame in frames)


async def test_conflict_when_turn_running_no_processing_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同会话已有运行中回合 → 409 且不落 processing 记录（被拒回合未发起）。"""
    monkeypatch.setattr("app.interfaces.http.chat._run_turn_events", _fake_events_normal)
    services, history, registry = _services()
    turn = ActiveTurn(message_id="m1")
    assert registry.register(_CONVERSATION_ID, turn) is True
    spin = asyncio.create_task(_spin_forever())
    turn.task = spin
    with pytest.raises(ConflictError):
        await chat_messages(
            ChatMessageRequest(query="你好", response_mode="blocking"),
            Response(),
            account_id="acct-1",
            services=services,
        )
    assert history.starts == []
    assert history.turns == []
    spin.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await spin
