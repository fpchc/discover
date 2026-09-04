"""单元测试：流式 / 阻塞回合的兜底落库（所有退出路径都落库）。

覆盖 _stream_sse 与 _blocking 的正常完成、客户端中断（任务取消 / 生成器
关闭）与服务端异常三种退出路径，断言 record_turn 被调用且 status / partial
内容正确。事件源统一用 RunEvent（v2 生命周期事件）；状态推导由
TurnRecorder 按终态事件映射 + exit_reason 兜底（react-runtime-v2-architecture
§17.1）。纯本地：注入伪事件源与伪历史服务，无网络无 DB。
"""

from collections.abc import AsyncIterator
from types import SimpleNamespace

import anyio
import pytest
from app.domain.conversation.recorder import ExitReason, TurnRecorder, resolve_turn_status
from app.interfaces.http.chat import _blocking, _stream_sse
from app.interfaces.schemas.conversations import ConversationSession, MessageStatus, TurnRecord
from app.runtime.events.run_events import (
    RunCancelled,
    RunCompleted,
    RunEvent,
    RunFailed,
    TextDelta,
    ThinkingDelta,
)
from app.runtime.models import TerminationReason
from app.runtime.turn import ActiveTurn, ActiveTurnRegistry
from app.shared.errors.base import ErrorCategory, PlatformError

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
    services: object, session: object, user_input: str, *, turn: object
) -> AsyncIterator[RunEvent]:
    """事件源：正常走完（正文 + 思考 + RunCompleted 终态）。"""
    del services, session, user_input, turn
    yield TextDelta(text="正文A")
    yield ThinkingDelta(text="思考B")
    yield RunCompleted(
        status="succeeded",
        termination_reason=TerminationReason.COMPLETED,
    )


async def _fake_events_cancel(
    services: object, session: object, user_input: str, *, turn: object
) -> AsyncIterator[RunEvent]:
    """事件源：产出部分正文后挂起，供外部取消 / 关闭。"""
    del services, session, user_input, turn
    yield TextDelta(text="部分正文")
    await anyio.sleep_forever()


async def _fake_events_boom(
    services: object, session: object, user_input: str, *, turn: object
) -> AsyncIterator[RunEvent]:
    """事件源：产出部分正文后抛未捕获异常。"""
    del services, session, user_input, turn
    yield TextDelta(text="正文A")
    raise RuntimeError("boom")


async def _fake_events_run_failed(
    services: object, session: object, user_input: str, *, turn: object
) -> AsyncIterator[RunEvent]:
    """事件源：产出正文后发 RunFailed（阻塞路径经 PlatformError 外抛）。"""
    del services, session, user_input, turn
    yield TextDelta(text="正文")
    yield RunFailed(
        error_category=ErrorCategory.AUTH,
        message="配额不足",
    )


async def test_stream_persists_normal_on_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.interfaces.http.chat._run_turn_events", _fake_events_normal)
    services = _make_services()
    frames: list[str] = []
    async for frame in _stream_sse(
        services, "查询", _make_session(), _MESSAGE_ID, _CREATED_AT, _make_turn()
    ):
        frames.append(frame)
    # message + thinking + message_end（RunCompleted 终态映射）
    assert len(frames) == 3
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
    monkeypatch.setattr("app.interfaces.http.chat._run_turn_events", _fake_events_cancel)
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
    monkeypatch.setattr("app.interfaces.http.chat._run_turn_events", _fake_events_cancel)
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
    monkeypatch.setattr("app.interfaces.http.chat._run_turn_events", _fake_events_boom)
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
    monkeypatch.setattr("app.interfaces.http.chat._run_turn_events", _fake_events_cancel)
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
    monkeypatch.setattr("app.interfaces.http.chat._run_turn_events", _fake_events_run_failed)
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
    assert resolve_turn_status("normal", None) is MessageStatus.NORMAL
    assert resolve_turn_status("interrupted", None) is MessageStatus.INTERRUPTED
    assert resolve_turn_status("error", None) is MessageStatus.ERROR
    # 服务端失败优先如实标记，即使终止原因是客户端中断
    assert resolve_turn_status("interrupted", "配额不足") is MessageStatus.ERROR


def test_turn_recorder_terminal_events_drive_status() -> None:
    """TurnRecorder 状态由 Run 终态事件显式映射（§17.1），exit_reason 兜底。"""
    recorder = TurnRecorder(message_id=_MESSAGE_ID, query="查询", session=_make_session())
    recorder.absorb(RunFailed(error_category=ErrorCategory.AUTH, message="配额不足"))
    assert recorder.build(exit_reason="normal").status is MessageStatus.ERROR
    assert recorder.build(exit_reason="normal").error == "配额不足"

    recorder_cancelled = TurnRecorder(message_id=_MESSAGE_ID, query="查询", session=_make_session())
    recorder_cancelled.absorb(RunCancelled(message="user_stop"))
    assert recorder_cancelled.build(exit_reason="normal").status is MessageStatus.INTERRUPTED

    recorder_partial = TurnRecorder(message_id=_MESSAGE_ID, query="查询", session=_make_session())
    recorder_partial.absorb(
        RunCompleted(status="partial", termination_reason=TerminationReason.TOKEN_BUDGET)
    )
    assert recorder_partial.build(exit_reason="normal").status is MessageStatus.PARTIAL

    recorder_succeeded = TurnRecorder(message_id=_MESSAGE_ID, query="查询", session=_make_session())
    recorder_succeeded.absorb(
        RunCompleted(status="succeeded", termination_reason=TerminationReason.COMPLETED)
    )
    assert recorder_succeeded.build(exit_reason="normal").status is MessageStatus.NORMAL

    recorder_no_terminal = TurnRecorder(
        message_id=_MESSAGE_ID, query="查询", session=_make_session()
    )
    exit_reason: ExitReason = "interrupted"
    assert recorder_no_terminal.build(exit_reason=exit_reason).status is MessageStatus.INTERRUPTED


def test_turn_recorder_accumulates_usage() -> None:
    """TurnRecorder 聚合 LLM 用量，compat_usage 输出对外 5 键形状。"""
    from app.runtime.events.run_events import LLMUsageUpdated

    recorder = TurnRecorder(message_id=_MESSAGE_ID, query="查询", session=_make_session())
    recorder.absorb(
        LLMUsageUpdated(usage={"input": 100, "output": 50, "total": 150, "cached_read": 5})
    )
    recorder.absorb(
        LLMUsageUpdated(usage={"input": 30, "output": 20, "total": 50, "cached_write": 3})
    )
    assert recorder.compat_usage() == {
        "prompt_tokens": 130,
        "completion_tokens": 70,
        "total_tokens": 200,
        "cached_read_tokens": 5,
        "cached_write_tokens": 3,
    }
    record = recorder.build(exit_reason="normal")
    assert record.usage.prompt_tokens == 130
    assert record.usage.cached_write_tokens == 3
