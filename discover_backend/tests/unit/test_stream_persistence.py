"""单元测试：流式 / 阻塞回合的兜底落库（所有退出路径都落库）。

覆盖 _stream_sse 与 _blocking 的正常完成、客户端中断（任务取消 / 生成器
关闭）与服务端异常三种退出路径，断言 record_turn 被调用且 status / partial
内容正确。纯本地：注入伪事件源与伪历史服务，无网络无 DB。
"""

from collections.abc import AsyncIterator
from types import SimpleNamespace

import anyio
import pytest
from app.api.chat import _blocking, _resolve_status, _stream_sse
from app.errors.base import ErrorCategory, PlatformError
from app.protocol.events import AgentEvent, ErrorEvent, TextDeltaEvent, ThinkingDeltaEvent
from app.runtime.active_turns import ActiveTurn, ActiveTurnRegistry
from app.schemas.conversations import ConversationSession, MessageStatus, TurnRecord

_MESSAGE_ID = "msg-interrupt-1"
_CONVERSATION_ID = "conv-1"
_CREATED_AT = 1700000000


class _FakeHistory:
    """伪历史服务：记录 record_turn 收到的载荷，供断言。"""

    def __init__(self) -> None:
        self.turns: list[TurnRecord] = []

    async def record_turn(self, conversation_id: str, turn: TurnRecord) -> bool:
        self.turns.append(turn)
        return True


def _make_services() -> SimpleNamespace:
    """最小 services 桩：conversation_service 供落库 + active_turns 供注销句柄。"""
    return SimpleNamespace(
        conversation_service=_FakeHistory(),
        active_turns=ActiveTurnRegistry(),
    )


def _make_turn(message_id: str = _MESSAGE_ID) -> ActiveTurn:
    """回合句柄桩：路由层同款（未注册，注销为 no-op）。"""
    return ActiveTurn(message_id=message_id)


def _make_session() -> ConversationSession:
    """真实会话 DTO：assistant_meta / agent_id_label 走属性而非桩字段。"""
    return ConversationSession(
        conversation_id=_CONVERSATION_ID,
        account_id="acct-1",
        assistant_target=None,
    )


async def _fake_events_normal(
    services: object, session: object, user_input: str
) -> AsyncIterator[AgentEvent]:
    """事件源：正常走完（正文 + 思考）。"""
    yield TextDeltaEvent(text="正文A")
    yield ThinkingDeltaEvent(text="思考B")


async def _fake_events_cancel(
    services: object, session: object, user_input: str
) -> AsyncIterator[AgentEvent]:
    """事件源：产出部分正文后挂起，供外部取消 / 关闭。"""
    yield TextDeltaEvent(text="部分正文")
    await anyio.sleep_forever()


async def _fake_events_boom(
    services: object, session: object, user_input: str
) -> AsyncIterator[AgentEvent]:
    """事件源：产出部分正文后抛未捕获异常。"""
    yield TextDeltaEvent(text="正文A")
    raise RuntimeError("boom")


async def _fake_events_platform_error(
    services: object, session: object, user_input: str
) -> AsyncIterator[AgentEvent]:
    """事件源：产出正文后发 ErrorEvent（阻塞路径经 PlatformError 外抛）。"""
    yield TextDeltaEvent(text="正文")
    yield ErrorEvent(
        category=ErrorCategory.AUTH,
        message="配额不足",
        recoverable=False,
        suggestion="请重试",
    )


async def test_stream_persists_normal_on_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.chat._run_turn_events", _fake_events_normal)
    services = _make_services()
    frames: list[str] = []
    async for frame in _stream_sse(
        services, "查询", _make_session(), _MESSAGE_ID, _CREATED_AT, _make_turn()
    ):
        frames.append(frame)
    assert len(frames) == 2  # message + thinking 帧
    history = services.conversation_service
    assert isinstance(history, _FakeHistory)
    assert len(history.turns) == 1
    turn = history.turns[0]
    assert turn.status == MessageStatus.NORMAL
    assert turn.query == "查询"
    assert turn.answer == "正文A"
    assert turn.thinking == "思考B"
    assert turn.message_id == _MESSAGE_ID
    assert turn.account_id == "acct-1"


async def test_stream_persists_interrupted_on_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.chat._run_turn_events", _fake_events_cancel)
    services = _make_services()

    async def _consume() -> None:
        async for _ in _stream_sse(
            services, "查询", _make_session(), _MESSAGE_ID, _CREATED_AT, _make_turn()
        ):
            pass

    with anyio.move_on_after(0.05):
        await _consume()
    history = services.conversation_service
    assert isinstance(history, _FakeHistory)
    assert len(history.turns) == 1
    turn = history.turns[0]
    assert turn.status == MessageStatus.INTERRUPTED
    assert turn.answer == "部分正文"
    assert turn.thinking is None


async def test_stream_persists_interrupted_on_aclose(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.chat._run_turn_events", _fake_events_cancel)
    services = _make_services()
    agen = _stream_sse(services, "查询", _make_session(), _MESSAGE_ID, _CREATED_AT, _make_turn())
    await anext(agen)
    await agen.aclose()
    history = services.conversation_service
    assert isinstance(history, _FakeHistory)
    assert len(history.turns) == 1
    turn = history.turns[0]
    assert turn.status == MessageStatus.INTERRUPTED
    assert turn.answer == "部分正文"


async def test_stream_persists_error_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.chat._run_turn_events", _fake_events_boom)
    services = _make_services()
    with pytest.raises(RuntimeError):
        async for _ in _stream_sse(
            services, "查询", _make_session(), _MESSAGE_ID, _CREATED_AT, _make_turn()
        ):
            pass
    history = services.conversation_service
    assert isinstance(history, _FakeHistory)
    assert len(history.turns) == 1
    turn = history.turns[0]
    assert turn.status == MessageStatus.ERROR
    assert turn.answer == "正文A"


async def test_blocking_persists_interrupted_on_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.chat._run_turn_events", _fake_events_cancel)
    services = _make_services()
    with anyio.move_on_after(0.05):
        await _blocking(services, "查询", _make_session(), _MESSAGE_ID, _CREATED_AT, _make_turn())
    history = services.conversation_service
    assert isinstance(history, _FakeHistory)
    assert len(history.turns) == 1
    turn = history.turns[0]
    assert turn.status == MessageStatus.INTERRUPTED
    assert turn.answer == "部分正文"


async def test_blocking_persists_error_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.chat._run_turn_events", _fake_events_platform_error)
    services = _make_services()
    with pytest.raises(PlatformError):
        await _blocking(services, "查询", _make_session(), _MESSAGE_ID, _CREATED_AT, _make_turn())
    history = services.conversation_service
    assert isinstance(history, _FakeHistory)
    assert len(history.turns) == 1
    turn = history.turns[0]
    assert turn.status == MessageStatus.ERROR
    assert turn.answer == "正文"
    assert turn.error == "配额不足"


def test_resolve_status_precedence() -> None:
    """状态推导：error 优先于 interrupted，interrupted 仅在客户端中断时生效。"""
    assert _resolve_status("normal", None) is MessageStatus.NORMAL
    assert _resolve_status("interrupted", None) is MessageStatus.INTERRUPTED
    assert _resolve_status("error", None) is MessageStatus.ERROR
    error = ErrorEvent(
        category=ErrorCategory.AUTH,
        message="配额不足",
        recoverable=False,
        suggestion="请重试",
    )
    # 服务端失败优先如实标记，即使终止原因是客户端中断
    assert _resolve_status("interrupted", error) is MessageStatus.ERROR
