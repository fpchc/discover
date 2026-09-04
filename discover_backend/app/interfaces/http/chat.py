"""对话接口（L4）：POST /chat-messages + POST /chat-messages/{id}/stop。

请求体 `{query, response_mode, conversation_id, ...}`；`conversation_id` 空串
自动创建会话（对话记录由 ConversationService.resolve 建行并归属当前账号），
续聊带上即复用（归属校验 404）。`streaming` 走 SSE（`data:` 帧，`event` 判别：
message / message_end / thinking_* / ping / error，以 message_end 收尾，无 [DONE]）；
`blocking` 返回 chat-messages JSON。

回合执行统一走 v2 Run 生命周期（react-runtime-v2-architecture §16/§17）：
RunService 创建 Run（快照 + 事件日志 + 租约），执行并发 RunEvent（展示增量 +
生命周期事件），SSE 帧映射由 run_stream.map_run_event 归一；回合结束由
TurnRecorder 聚合 RunEvent 流并经 conversation_service.record_turn 落库。
stop 接口持久化走 RunService.cancel（事件日志记录 RunCancelled），执行中断仍由
路由层 task.cancel() 承担（与客户端断开同一取消原语；同会话并发二次发起 → 409，
见 ActiveTurnRegistry）。

单一职责（CLAUDE.md §13.1）：本文件只保留 HTTP 接入职责——参数提取、响应帧
映射、回合落库转调与 ActiveTurn 注册/注销；回合执行（Run 创建 / 专家与通用
两条执行路径 / 终态事件）下沉到 chat_execution.py，历史加载与用量聚合亦归执行层。
对话记录生命周期（创建/归属/绑定/标题）全部由 ConversationService 管理。
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator

import anyio
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.bootstrap.container import AppServices, get_services
from app.domain.conversation.recorder import ExitReason, TurnRecorder
from app.interfaces.http.chat_execution import _run_turn_events
from app.interfaces.http.deps import get_current_account_id
from app.interfaces.http.run_stream import is_terminal, map_run_event
from app.interfaces.schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatStopResponse,
    ConversationSession,
    ErrorStreamEvent,
    MessageEndEvent,
    MessageEvent,
    PingEvent,
    ThinkingDeltaFrame,
    ThinkingEndFrame,
    ThinkingStartFrame,
)
from app.runtime.turn import ActiveTurn
from app.shared.errors.base import ConflictError, ErrorCategory, PlatformError

router = APIRouter(tags=["chat"])

logger = logging.getLogger(__name__)

# 对外 SSE 帧判别联合（event 字段判别）；与 run_stream._StreamFrame 同构
_StreamFrame = (
    MessageEvent
    | MessageEndEvent
    | PingEvent
    | ErrorStreamEvent
    | ThinkingStartFrame
    | ThinkingDeltaFrame
    | ThinkingEndFrame
)


@router.post("/chat-messages", response_model=None)
async def chat_messages(
    body: ChatMessageRequest,
    response: Response,
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> StreamingResponse | ChatMessageResponse:
    """对话：会话缺省自动创建（归属当前账号），续聊带 conversation_id。

    路由层登记 ActiveTurn（早于响应返回，覆盖「已创建未消费」窗口）：同会话
    已有进行中回合 → 409（底层 Runtime 非并发安全，禁止并发回合）。
    """
    assert services.conversation_service is not None
    session = await services.conversation_service.resolve(
        account_id=account_id,
        conversation_id=body.conversation_id,
        agent_id=body.agent_id,
        query=body.query,
    )
    conversation_id = session.conversation_id
    response.headers["X-Conversation-Id"] = conversation_id
    message_id = uuid.uuid4().hex
    created_at = int(time.time())
    turn = ActiveTurn(message_id=message_id)
    if not services.active_turns.register(conversation_id, turn):
        raise ConflictError("会话正在进行中的回合，请先停止或等待完成")
    if body.response_mode == "streaming":
        return StreamingResponse(
            _stream_sse(services, body.query, session, message_id, created_at, turn),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 显式禁用反向代理缓冲
                "X-Conversation-Id": conversation_id,
            },
        )
    return await _blocking(services, body.query, session, message_id, created_at, turn)


@router.post("/chat-messages/{conversation_id}/stop", response_model=ChatStopResponse)
async def stop_chat_message(
    conversation_id: str,
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> ChatStopResponse:
    """停止会话的进行中回合：持久化 RunService.cancel + task.cancel() 中断执行。

    归属校验走严格读（未知 / 跨账号 / 已软删 → 404，不泄露存在性）；无进行中
    回合返回 idle。stopping 只承诺取消已请求，前端以 SSE 流关闭为准。
    """
    assert services.conversation_service is not None
    await services.conversation_service.require_owned(account_id, conversation_id)
    turn = services.active_turns.request_stop(conversation_id)
    if turn is None:
        return ChatStopResponse(conversation_id=conversation_id, status="idle")
    if turn.run_id is not None:
        await services.run_service.cancel(turn.run_id, source="user_stop")
    return ChatStopResponse(
        conversation_id=conversation_id, status="stopping", message_id=turn.message_id
    )


async def _blocking(
    services: AppServices,
    user_input: str,
    session: ConversationSession,
    message_id: str,
    created_at: int,
    turn: ActiveTurn,
) -> ChatMessageResponse:
    """blocking：聚合 RunEvent 流，返回 chat-messages JSON。

    turn.task 捕获当前请求任务供 stop 取消；预启动窗口的 stop（stop_requested）
    在启动时立即中断。取消/异常路径先落库后注销（与 _stream_sse 一致的顺序）。
    """
    recorder = TurnRecorder(message_id=message_id, query=user_input, session=session)
    exit_reason: ExitReason = "normal"
    turn.task = asyncio.current_task()
    try:
        if turn.stop_requested:
            raise asyncio.CancelledError
        async for event in _run_turn_events(services, session, user_input, turn=turn):
            recorder.absorb(event)
    except asyncio.CancelledError:
        # 客户端断开 / 服务端 stop：聚合的部分内容照常落库（interrupted），再向外传播取消
        exit_reason = "interrupted"
        raise
    except Exception:
        exit_reason = "error"
        raise
    finally:
        await _persist_turn(services, session, recorder, exit_reason=exit_reason)
        services.active_turns.unregister(session.conversation_id, turn)
    if recorder.error is not None:
        raise PlatformError(
            recorder.error,
            category=recorder.error_category or ErrorCategory.SERVER,
            retryable=recorder.recoverable,
        )
    metadata: dict[str, object] = {"usage": recorder.compat_usage()}
    assistant = session.assistant_meta
    if assistant is not None:
        metadata["assistant"] = assistant
    record = recorder.build(exit_reason=exit_reason)
    return ChatMessageResponse(
        message_id=message_id,
        answer=record.answer or "",
        metadata=metadata,
        conversation_id=session.conversation_id,
        created_at=created_at,
    )


async def _stream_sse(
    services: AppServices,
    user_input: str,
    session: ConversationSession,
    message_id: str,
    created_at: int,
    turn: ActiveTurn,
) -> AsyncIterator[str]:
    """流式：RunEvent 经 map_run_event 归一为 `event` 判别帧，以 message_end 收尾。

    日志观测：记录流生命周期与终止原因（正常走完 / 生成器关闭 / 任务取消 /
    异常）。所有退出路径（正常 / 客户端中断 / 服务端异常）都兜底落库一次，
    中断回合保留 query + partial 内容，供历史可查。

    turn.task 捕获真正承载生成的任务（供 stop 跨任务取消）；先置 task 再查
    stop_requested，保证预启动 stop 不落空。服务端 stop 与客户端断连共用同一
    取消原语（task.cancel()），统一落入 except(GeneratorExit, CancelledError)。
    """
    recorder = TurnRecorder(message_id=message_id, query=user_input, session=session)
    assistant = session.assistant_meta
    exit_reason: ExitReason = "normal"
    turn.task = asyncio.current_task()
    logger.info(
        "SSE 流开始",
        extra={
            "message_id": message_id,
            "conversation_id": session.conversation_id,
            "agent_id": session.agent_id_label,
            "query_len": len(user_input),
        },
    )
    try:
        if turn.stop_requested:
            raise asyncio.CancelledError
        async for event in _run_turn_events(services, session, user_input, turn=turn):
            recorder.absorb(event)
            frame = map_run_event(
                event,
                message_id=message_id,
                conversation_id=session.conversation_id,
                created_at=created_at,
                usage=recorder.compat_usage() if is_terminal(event) else None,
                assistant=assistant if is_terminal(event) else None,
            )
            if frame is not None:
                yield _sse_frame(frame)
    except (GeneratorExit, asyncio.CancelledError):
        # 客户端断开（aclose/task cancel）与服务端 stop 统一视为中断：保留 partial
        exit_reason = "interrupted"
        logger.warning(
            "SSE 流被中断（客户端断开 / 服务端 stop）",
            extra={"message_id": message_id, "conversation_id": session.conversation_id},
        )
        raise
    except Exception:
        exit_reason = "error"
        logger.exception(
            "SSE 流异常终止",
            extra={"message_id": message_id, "conversation_id": session.conversation_id},
        )
        raise
    finally:
        # 兜底落库：无论正常 / 中断 / 异常都记录一回合，保证前端中途中断的
        # 对话也有 message。DB 降级由 record_turn 内部消化，落库失败不掩盖
        # 原始终止原因（异常 / 取消继续向外传播）。落库完成后注销句柄。
        await _persist_turn(services, session, recorder, exit_reason=exit_reason)
        services.active_turns.unregister(session.conversation_id, turn)
        text = recorder.answer
        thinking = recorder.thinking
        logger.info(
            "SSE 流退出",
            extra={
                "message_id": message_id,
                "conversation_id": session.conversation_id,
                "exit_reason": exit_reason,
                "text_len": len(text),
                "thinking_len": len(thinking),
                "has_error": recorder.error is not None,
            },
        )


async def _persist_turn(
    services: AppServices,
    session: ConversationSession,
    recorder: TurnRecorder,
    *,
    exit_reason: ExitReason,
) -> None:
    """回合结束落库一次；DB 降级由服务内部消化（路由无感知）。

    状态由 recorder 按 Run 终态事件显式推导（RunCompleted → normal / RunFailed →
    error / RunCancelled → interrupted），缺失时按 exit_reason 兜底（§17.1）。
    """
    if services.conversation_service is None:
        return
    turn = recorder.build(exit_reason=exit_reason)
    # 中断/异常路径在取消传播途中落库：anyio 取消 scope 语义下，取消请求后
    # 任何 checkpoint 会再次收到 CancelledError，DB 写入会被打断；shield 保护
    # 写入完成（best-effort），随后取消继续向外传播。
    with anyio.CancelScope(shield=True):
        await services.conversation_service.record_turn(session.conversation_id, turn)


def _sse_frame(event: _StreamFrame) -> str:
    return f"data: {event.model_dump_json()}\n\n"
