"""对话接口（接入层）：POST /chat-messages + POST /chat-messages/{id}/stop。

请求体 `{query, response_mode, conversation_id, ...}`；`conversation_id` 空串
自动创建会话（ConversationService.resolve 建行并归属当前账号），续聊带上即复用
（归属校验 404）。`streaming` 走 SSE（`data:` 帧，`event` 判别：
message / message_end / thinking_* / ping / error，以 message_end 收尾，无 [DONE]）；
`blocking` 返回 chat-messages JSON。

单一职责（CLAUDE.md §13.1）：本文件只做**协议适配**——参数提取、帧编码、
HTTP 响应构造。回合编排（并发登记 / 执行 / 终态注销 / 兜底落库）在
`app/application/chat/turn_lifecycle.py`；RunEvent → SSE 帧映射在
`app/interfaces/sse/frames.py`。
"""

import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.application.chat.turn_lifecycle import collect_turn, iter_turn_events, start_turn
from app.application.dto import ConversationSession
from app.application.services import AppServices
from app.harness.turn import ActiveTurn
from app.interfaces.http.auth_guard import LoginRoute, login_required
from app.interfaces.http.deps import get_current_account_id, get_services
from app.interfaces.schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatStopResponse,
    ErrorStreamEvent,
    MessageEndEvent,
    MessageEvent,
    PingEvent,
    ThinkingDeltaFrame,
    ThinkingEndFrame,
    ThinkingStartFrame,
)
from app.interfaces.sse.frames import map_run_event

router = APIRouter(tags=["chat"], route_class=LoginRoute)

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
@login_required
async def chat_messages(
    body: ChatMessageRequest,
    response: Response,
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> StreamingResponse | ChatMessageResponse:
    """对话：会话缺省自动创建（归属当前账号），续聊带 conversation_id。

    回合登记早于响应返回（覆盖「已创建未消费」窗口）：同会话已有进行中
    回合 → 409（底层 Runtime 非并发安全，禁止并发回合）。
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
    turn = await start_turn(
        services,
        session=session,
        account_id=account_id,
        user_input=body.query,
        message_id=message_id,
    )
    if body.response_mode == "streaming":
        return StreamingResponse(
            stream_sse(services, body.query, session, message_id, created_at, turn),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 显式禁用反向代理缓冲
                "X-Conversation-Id": conversation_id,
            },
        )
    return await run_blocking(services, body.query, session, message_id, created_at, turn)


@router.post("/chat-messages/{conversation_id}/stop", response_model=ChatStopResponse)
@login_required
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


async def stream_sse(
    services: AppServices,
    user_input: str,
    session: ConversationSession,
    message_id: str,
    created_at: int,
    turn: ActiveTurn,
) -> AsyncIterator[str]:
    """流式：回合事件经 map_run_event 归一为 `event` 判别帧，以 message_end 收尾。

    所有退出路径（正常 / 客户端中断 / 服务端异常）由生命周期层兜底落库一次，
    中断回合保留 query + partial 内容，供历史可查。
    """
    events = iter_turn_events(
        services, session=session, user_input=user_input, message_id=message_id, turn=turn
    )
    # 客户端断连时外层生成器被 aclose，必须显式关闭内层生成器，才能让
    # 生命周期层的 finally 兜底落库（否则要等 GC 才终结，落库时机不可控）。
    try:
        async for item in events:
            frame = map_run_event(
                item.event,
                message_id=message_id,
                conversation_id=session.conversation_id,
                created_at=created_at,
                usage=item.usage,
                assistant=item.assistant,
            )
            if frame is not None:
                yield sse_frame(frame)
    finally:
        await events.aclose()


async def run_blocking(
    services: AppServices,
    user_input: str,
    session: ConversationSession,
    message_id: str,
    created_at: int,
    turn: ActiveTurn,
) -> ChatMessageResponse:
    """blocking：聚合整轮事件后返回 chat-messages JSON。"""
    outcome = await collect_turn(
        services, session=session, user_input=user_input, message_id=message_id, turn=turn
    )
    metadata: dict[str, object] = {"usage": outcome.usage}
    if outcome.assistant is not None:
        metadata["assistant"] = outcome.assistant
    return ChatMessageResponse(
        message_id=message_id,
        answer=outcome.record.answer or "",
        metadata=metadata,
        conversation_id=session.conversation_id,
        created_at=created_at,
    )


def sse_frame(event: _StreamFrame) -> str:
    """SSE 线格式：`data: <json>` + 空行分隔。"""
    return f"data: {event.model_dump_json()}\n\n"


__all__ = [
    "chat_messages",
    "router",
    "run_blocking",
    "sse_frame",
    "stop_chat_message",
    "stream_sse",
]
