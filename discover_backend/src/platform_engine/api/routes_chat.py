"""对话接口（L4）：POST /chat-messages。

请求体 `{query, response_mode, conversation_id, ...}`；`conversation_id` 空串
自动创建会话，续聊带上即复用会话状态（服务端持有历史）。`streaming` 走 SSE
（`data:` 帧，`event` 判别：message / message_end / ping / error，以
message_end 收尾，无 [DONE]）；`blocking` 返回 chat-messages JSON。
图执行与 SSE 写循环在同一任务组：客户端断开即取消图执行并释放会话资源
（异常路径亦然）。
"""

import time
import uuid
from collections.abc import AsyncIterator

import anyio
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from platform_engine.api.deps import AppServices, get_services
from platform_engine.api.models import (
    ChatMessageRequest,
    ChatMessageResponse,
    ErrorStreamEvent,
    MessageEndEvent,
    MessageEvent,
    PingEvent,
    ThinkingDeltaFrame,
    ThinkingEndFrame,
    ThinkingStartFrame,
)
from platform_engine.errors.base import ErrorCategory, PlatformError
from platform_engine.protocol.emitter import QueueEmitter
from platform_engine.protocol.events import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    HeartbeatEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ThinkingEndedEvent,
    ThinkingStartedEvent,
)
from platform_engine.protocol.sanitize import sanitize_error_message

router = APIRouter(tags=["chat"])

_POLL_SECONDS = 0.1

_ERROR_STATUS = {
    ErrorCategory.NOT_FOUND: 404,
    ErrorCategory.INVALID_ARGUMENT: 400,
    ErrorCategory.AUTH: 401,
    ErrorCategory.DENIED: 403,
    ErrorCategory.BAD_REQUEST: 400,
    ErrorCategory.CONFIG: 500,
}


@router.post("/chat-messages", response_model=None)
async def chat_messages(
    body: ChatMessageRequest,
    response: Response,
    services: AppServices = Depends(get_services),
) -> StreamingResponse | ChatMessageResponse:
    """对话：会话缺省自动创建，续聊带 conversation_id。"""
    assert services.sessions is not None
    conversation_id = await _resolve_conversation(services, body.conversation_id)
    response.headers["X-Conversation-Id"] = conversation_id
    message_id = uuid.uuid4().hex
    created_at = int(time.time())
    if body.response_mode == "streaming":
        return StreamingResponse(
            _stream_sse(services, body.query, conversation_id, message_id, created_at),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 显式禁用反向代理缓冲
                "X-Conversation-Id": conversation_id,
            },
        )
    return await _blocking(services, body.query, conversation_id, message_id, created_at)


async def _resolve_conversation(services: AppServices, conversation_id: str) -> str:
    """会话解析：空串自动创建；显式传入则校验存在（不存在 → 404）。"""
    assert services.sessions is not None
    if not conversation_id.strip():
        record = await services.sessions.create_session()
        return record.session_id
    conversation_id = conversation_id.strip()
    services.sessions.get_session(conversation_id)
    return conversation_id


async def _blocking(
    services: AppServices,
    user_input: str,
    conversation_id: str,
    message_id: str,
    created_at: int,
) -> ChatMessageResponse:
    """blocking：聚合正文增量，返回 chat-messages JSON。"""
    text_parts: list[str] = []
    usage: dict[str, int] = {}
    error_event: ErrorEvent | None = None
    async for event in _run_turn_events(services, conversation_id, user_input):
        if isinstance(event, TextDeltaEvent):
            text_parts.append(event.text)
        elif isinstance(event, DoneEvent):
            usage = event.usage
        elif isinstance(event, ErrorEvent):
            error_event = event
    if error_event is not None:
        raise PlatformError(
            error_event.message,
            category=error_event.category,
            retryable=error_event.recoverable,
        )
    return ChatMessageResponse(
        message_id=message_id,
        answer="".join(text_parts),
        metadata={"usage": _compat_usage(usage)},
        conversation_id=conversation_id,
        created_at=created_at,
    )


async def _stream_sse(
    services: AppServices,
    user_input: str,
    conversation_id: str,
    message_id: str,
    created_at: int,
) -> AsyncIterator[str]:
    """流式：内部事件转 `event` 判别帧，以 message_end 收尾。"""
    async for event in _run_turn_events(services, conversation_id, user_input):
        frame = _map_stream_event(
            event,
            message_id=message_id,
            conversation_id=conversation_id,
            created_at=created_at,
        )
        if frame is not None:
            yield _sse_frame(frame)


def _compat_usage(usage: dict[str, int]) -> dict[str, int]:
    """内部 usage（input/output/total）映射为对外兼容形状。"""
    return {
        "prompt_tokens": usage.get("input", 0),
        "completion_tokens": usage.get("output", 0),
        "total_tokens": usage.get("total", 0),
    }


# 对外 SSE 帧判别联合（event 字段判别）；tests/http/test_api.py 维护同构联合
_StreamFrame = (
    MessageEvent
    | MessageEndEvent
    | PingEvent
    | ErrorStreamEvent
    | ThinkingStartFrame
    | ThinkingDeltaFrame
    | ThinkingEndFrame
)


def _map_stream_event(
    event: AgentEvent,
    *,
    message_id: str,
    conversation_id: str,
    created_at: int,
) -> _StreamFrame | None:
    """内部 AgentEvent → 对外 SSE 帧（纯函数，便于单测）。

    思考事件独立映射为 thinking_* 帧，供前端渲染 DeepSeek 式思考分区，
    与正文 message 帧（打字机）区分；路由/工具/产物等富事件在对外流中
    丢弃（返回 None）。
    """
    if isinstance(event, ThinkingStartedEvent):
        return ThinkingStartFrame(
            message_id=message_id,
            conversation_id=conversation_id,
            created_at=created_at,
        )
    if isinstance(event, ThinkingDeltaEvent):
        return ThinkingDeltaFrame(
            message_id=message_id,
            conversation_id=conversation_id,
            content=event.text,
            created_at=created_at,
        )
    if isinstance(event, ThinkingEndedEvent):
        return ThinkingEndFrame(
            message_id=message_id,
            conversation_id=conversation_id,
            duration_ms=event.duration_ms,
            created_at=created_at,
        )
    if isinstance(event, HeartbeatEvent):
        return PingEvent()
    if isinstance(event, TextDeltaEvent):
        return MessageEvent(
            message_id=message_id,
            conversation_id=conversation_id,
            answer=event.text,
            created_at=created_at,
        )
    if isinstance(event, ErrorEvent):
        return ErrorStreamEvent(
            status=_ERROR_STATUS.get(event.category, 500),
            code=event.category.value,
            message=event.message,
        )
    if isinstance(event, DoneEvent):
        return MessageEndEvent(
            message_id=message_id,
            conversation_id=conversation_id,
            metadata={"usage": _compat_usage(event.usage)},
            created_at=created_at,
        )
    return None


def _sse_frame(event: _StreamFrame) -> str:
    return f"data: {event.model_dump_json()}\n\n"


async def _run_turn_events(
    services: AppServices, conversation_id: str, user_input: str
) -> AsyncIterator[AgentEvent]:
    """执行单轮并逐个产出事件。"""
    emitter = QueueEmitter(services.settings)
    done = anyio.Event()

    async def run_graph() -> None:
        runtime = services.get_runtime(conversation_id)
        try:
            await runtime.run_turn(
                session_id=conversation_id, user_input=user_input, emitter=emitter
            )
        except PlatformError as exc:
            await emitter.emit(
                ErrorEvent(
                    category=exc.category,
                    message=sanitize_error_message(
                        str(exc), max_length=services.settings.error_message_max_chars
                    ),
                    recoverable=exc.retryable,
                    suggestion=None,
                )
            )
        except Exception:
            await emitter.emit(
                ErrorEvent(
                    category=ErrorCategory.SERVER,
                    message="内部错误",
                    recoverable=False,
                    suggestion="请重试",
                )
            )
        finally:
            await emitter.finish()
            done.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(emitter.run)
        tg.start_soon(run_graph)
        while True:
            event = await _next_event(emitter, done)
            if event is None:
                break
            yield event
        # 自然流尾：任务组 __aexit__ 会等待所有子任务结束，emitter.run 是
        # 常驻协程，必须显式取消，否则退出永不返回（流尾挂死）。
        tg.cancel_scope.cancel()


async def _next_event(emitter: QueueEmitter, done: anyio.Event) -> AgentEvent | None:
    """取下一个事件。done 置位且队列排空后返回 None 结束流。"""
    while True:
        try:
            with anyio.fail_after(_POLL_SECONDS):
                return await emitter.get()
        except TimeoutError:
            if done.is_set():
                return None
