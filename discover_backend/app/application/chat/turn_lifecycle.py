"""回合生命周期（application/chat）：并发登记、执行、终态注销与兜底落库。

单一动机：把「一个回合从登记到落库」的编排从 HTTP 路由移出，使接入层只剩
协议职责（参数提取、帧编码）。三条硬约束在这里集中实现，避免散落：

1. **同会话并发 409**：登记早于响应返回，覆盖「已创建未消费」窗口；
2. **锁在终态释放**：客户端收到终态帧即可发起下一回合，落库不占锁；
3. **所有退出路径兜底落库一次**：正常 / 客户端断连 / 服务端 stop / 异常，
   中断回合保留 partial 内容；写入经 CancelScope(shield=True) 保护。

本模块不产出任何 HTTP/SSE 形状（帧编码在 `app/interfaces/sse/`）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

import anyio
from pydantic import BaseModel

from app.application.chat.run_turn import run_turn_events
from app.application.conversation.recorder import ExitReason, TurnRecorder
from app.application.dto import ConversationSession, TurnRecord, TurnStartRecord
from app.application.services import AppServices
from app.harness.events.run_events import RunEvent, is_terminal
from app.harness.turn import ActiveTurn
from app.shared.errors.base import ConflictError, ErrorCategory, PlatformError

logger = logging.getLogger(__name__)


class TurnEvent(BaseModel):
    """对外暴露的单条回合事件：终态事件附带用量与助手元信息快照。"""

    event: RunEvent
    usage: dict[str, int] | None = None
    assistant: dict[str, str | None] | None = None


class TurnOutcome(BaseModel):
    """blocking 路径的回合结果：落库记录 + 响应元数据。"""

    record: TurnRecord
    usage: dict[str, int]
    assistant: dict[str, str | None] | None = None


async def start_turn(
    services: AppServices,
    *,
    session: ConversationSession,
    account_id: str,
    user_input: str,
    message_id: str,
) -> ActiveTurn:
    """登记进行中回合并落 processing 记录（仅 query，best-effort）。

    登记失败（同会话已有进行中回合）抛 ConflictError → 路由转 409。
    """
    assert services.conversation_service is not None
    turn = ActiveTurn(message_id=message_id)
    if not services.active_turns.register(session.conversation_id, turn):
        raise ConflictError("会话正在进行中的回合，请先停止或等待完成")
    await services.conversation_service.start_turn(
        session.conversation_id,
        TurnStartRecord(
            message_id=message_id,
            query=user_input,
            account_id=account_id,
            agent_id=session.agent_id_label,
        ),
    )
    return turn


async def iter_turn_events(
    services: AppServices,
    *,
    session: ConversationSession,
    user_input: str,
    message_id: str,
    turn: ActiveTurn,
    recorder: TurnRecorder | None = None,
) -> AsyncGenerator[TurnEvent, None]:
    """执行回合并逐个产出 `TurnEvent`（含终态快照与退出兜底落库）。

    turn.task 捕获真正承载回合的任务（服务端 stop 与客户端断连共用同一取消
    原语）；先置 task 再查 stop_requested，保证预启动 stop 不落空。
    """
    recorder = recorder or TurnRecorder(message_id=message_id, query=user_input, session=session)
    exit_reason: ExitReason = "normal"
    turn.task = asyncio.current_task()
    try:
        if turn.stop_requested:
            raise asyncio.CancelledError
        async for event in run_turn_events(services, session, user_input, turn=turn):
            recorder.absorb(event)
            terminal = is_terminal(event)
            # 终态事件处理即释放会话锁：客户端拿到终态帧时锁已空闲，
            # 可立即发起下一回合；收尾落库不占锁。
            if terminal:
                services.active_turns.unregister(session.conversation_id, turn)
            yield TurnEvent(
                event=event,
                usage=recorder.compat_usage() if terminal else None,
                assistant=session.assistant_meta if terminal else None,
            )
    except (GeneratorExit, asyncio.CancelledError):
        # 客户端断开（aclose/task cancel）与服务端 stop 统一视为中断：保留 partial
        exit_reason = "interrupted"
        logger.warning(
            "回合被中断（客户端断开 / 服务端 stop）",
            extra={"message_id": message_id, "conversation_id": session.conversation_id},
        )
        raise
    except Exception:
        exit_reason = "error"
        logger.exception(
            "回合异常终止",
            extra={"message_id": message_id, "conversation_id": session.conversation_id},
        )
        raise
    finally:
        # 先注销回合句柄（释放会话锁）再兜底落库：落库耗时不再占锁；
        # DB 降级由 record_turn 内部消化，落库失败不掩盖原始终止原因。
        services.active_turns.unregister(session.conversation_id, turn)
        try:
            await _persist_turn(services, session, recorder, exit_reason=exit_reason)
        except Exception:
            logger.exception(
                "回合落库异常（best-effort 忽略）",
                extra={"message_id": message_id, "conversation_id": session.conversation_id},
            )
        logger.info(
            "回合退出",
            extra={
                "message_id": message_id,
                "conversation_id": session.conversation_id,
                "exit_reason": exit_reason,
                "text_len": len(recorder.answer),
                "thinking_len": len(recorder.thinking),
                "has_error": recorder.error is not None,
            },
        )


async def collect_turn(
    services: AppServices,
    *,
    session: ConversationSession,
    user_input: str,
    message_id: str,
    turn: ActiveTurn,
) -> TurnOutcome:
    """blocking 路径：聚合整轮事件，返回落库记录与响应元数据。

    回合内失败经 PlatformError 上抛（统一异常中间件转错误响应）。
    """
    recorder = TurnRecorder(message_id=message_id, query=user_input, session=session)
    exit_reason: ExitReason = "normal"
    # 事件已由 iter_turn_events 就地聚合进同一 recorder，此处只驱动消费。
    async for _ in iter_turn_events(
        services,
        session=session,
        user_input=user_input,
        message_id=message_id,
        turn=turn,
        recorder=recorder,
    ):
        pass
    outcome_record = recorder.build(exit_reason=exit_reason)
    if recorder.error is not None:
        raise PlatformError(
            recorder.error,
            category=recorder.error_category or ErrorCategory.SERVER,
            retryable=recorder.recoverable,
        )
    return TurnOutcome(
        record=outcome_record,
        usage=recorder.compat_usage(),
        assistant=session.assistant_meta,
    )


async def _persist_turn(
    services: AppServices,
    session: ConversationSession,
    recorder: TurnRecorder,
    *,
    exit_reason: ExitReason,
) -> None:
    """回合结束更新落库一次（start_turn 建的 processing 记录 → 终态）。

    状态由 recorder 按 Run 终态事件显式推导（RunCompleted → normal / RunFailed →
    error / RunCancelled → interrupted），缺失时按 exit_reason 兜底（§17.1）。
    DB 降级由服务内部消化（调用方无感知）。
    """
    if services.conversation_service is None:
        return
    turn_record = recorder.build(exit_reason=exit_reason)
    # 中断/异常路径在取消传播途中落库：anyio 取消 scope 语义下，取消请求后
    # 任何 checkpoint 会再次收到 CancelledError，DB 写入会被打断；shield 保护
    # 写入完成（best-effort），随后取消继续向外传播。
    with anyio.CancelScope(shield=True):
        await services.conversation_service.record_turn(session.conversation_id, turn_record)


__all__ = ["TurnEvent", "TurnOutcome", "collect_turn", "iter_turn_events", "start_turn"]
