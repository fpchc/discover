"""对话接口（L4）：POST /chat-messages。

请求体 `{query, response_mode, conversation_id, ...}`；`conversation_id` 空串
自动创建会话（对话记录由 ConversationService.resolve 建行并归属当前账号），
续聊带上即复用（归属校验 404）。`streaming` 走 SSE（`data:` 帧，`event` 判别：
message / message_end / ping / error，以 message_end 收尾，无 [DONE]）；
`blocking` 返回 chat-messages JSON。图执行与 SSE 写循环在同一任务组：
客户端断开即取消图执行并释放会话资源（异常路径亦然）。

对话记录生命周期（创建/归属/绑定/标题）全部由 ConversationService 管理，
路由只做参数提取与转调（CLAUDE.md §13 内聚/耦合）；历史落库回合结束统一调
`record_turn`（正常与 error 皆记录），DB 降级由服务内部消化，路由无 try/except。
"""

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import anyio
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_account_id
from app.container import AppServices, get_services
from app.errors.base import ErrorCategory, PlatformError, http_status_for
from app.protocol.emitter import QueueEmitter
from app.protocol.events import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    HeartbeatEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ThinkingEndedEvent,
    ThinkingStartedEvent,
)
from app.protocol.sanitize import sanitize_error_message
from app.schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ConversationSession,
    ErrorStreamEvent,
    MessageEndEvent,
    MessageEvent,
    MessageStatus,
    PingEvent,
    ThinkingDeltaFrame,
    ThinkingEndFrame,
    ThinkingStartFrame,
    TurnRecord,
    TurnUsage,
)

router = APIRouter(tags=["chat"])

_POLL_SECONDS = 0.1


@dataclass
class _TurnCollector:
    """单回合事件收集：聚合正文/思考/usage/provider/error，供落库。"""

    # pragma: 简化 — 回合内部事件收集器，不跨边界序列化，无需 pydantic

    text_parts: list[str] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    provider: str | None = None
    model: str | None = None
    duration_ms: int = 0
    error: ErrorEvent | None = None

    def absorb(self, event: AgentEvent) -> None:
        if isinstance(event, TextDeltaEvent):
            self.text_parts.append(event.text)
        elif isinstance(event, ThinkingDeltaEvent):
            self.thinking_parts.append(event.text)
        elif isinstance(event, DoneEvent):
            self.usage = event.usage
            self.provider = event.provider
            self.model = event.model
            self.duration_ms = event.duration_ms
        elif isinstance(event, ErrorEvent):
            self.error = event


@router.post("/chat-messages", response_model=None)
async def chat_messages(
    body: ChatMessageRequest,
    response: Response,
    account_id: str = Depends(get_current_account_id),
    services: AppServices = Depends(get_services),
) -> StreamingResponse | ChatMessageResponse:
    """对话：会话缺省自动创建（归属当前账号），续聊带 conversation_id。"""
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
    if body.response_mode == "streaming":
        return StreamingResponse(
            _stream_sse(services, body.query, session, message_id, created_at),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 显式禁用反向代理缓冲
                "X-Conversation-Id": conversation_id,
            },
        )
    return await _blocking(services, body.query, session, message_id, created_at)


async def _blocking(
    services: AppServices,
    user_input: str,
    session: ConversationSession,
    message_id: str,
    created_at: int,
) -> ChatMessageResponse:
    """blocking：聚合正文增量，返回 chat-messages JSON。"""
    collector = _TurnCollector()
    async for event in _run_turn_events(services, session, user_input):
        collector.absorb(event)
    await _persist_turn(services, session, message_id, user_input, collector)
    if collector.error is not None:
        raise PlatformError(
            collector.error.message,
            category=collector.error.category,
            retryable=collector.error.recoverable,
        )
    metadata: dict[str, object] = {"usage": _compat_usage(collector.usage)}
    assistant = session.assistant_meta
    if assistant is not None:
        metadata["assistant"] = assistant
    return ChatMessageResponse(
        message_id=message_id,
        answer="".join(collector.text_parts),
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
) -> AsyncIterator[str]:
    """流式：内部事件转 `event` 判别帧，以 message_end 收尾；流尾落库。"""
    collector = _TurnCollector()
    assistant = session.assistant_meta
    async for event in _run_turn_events(services, session, user_input):
        collector.absorb(event)
        frame = _map_stream_event(
            event,
            message_id=message_id,
            conversation_id=session.conversation_id,
            created_at=created_at,
            assistant=assistant,
        )
        if frame is not None:
            yield _sse_frame(frame)
    await _persist_turn(services, session, message_id, user_input, collector)


async def _persist_turn(
    services: AppServices,
    session: ConversationSession,
    message_id: str,
    user_input: str,
    collector: _TurnCollector,
) -> None:
    """回合结束落库一次；DB 降级由服务内部消化（路由无感知）。"""
    if services.conversation_service is None:
        return
    turn = TurnRecord(
        message_id=message_id,
        query=user_input,
        answer="".join(collector.text_parts) or None,
        thinking="".join(collector.thinking_parts) or None,
        status=MessageStatus.ERROR if collector.error is not None else MessageStatus.NORMAL,
        error=collector.error.message if collector.error is not None else None,
        agent_id=session.agent_id_label,
        provider=collector.provider,
        model=collector.model,
        latency_ms=collector.duration_ms,
        usage=TurnUsage(
            prompt_tokens=collector.usage.get("input", 0),
            completion_tokens=collector.usage.get("output", 0),
            total_tokens=collector.usage.get("total", 0),
            cached_read_tokens=collector.usage.get("cached_read", 0),
            cached_write_tokens=collector.usage.get("cached_write", 0),
        ),
        account_id=session.account_id,
    )
    await services.conversation_service.record_turn(session.conversation_id, turn)


def _compat_usage(usage: dict[str, int]) -> dict[str, int]:
    """内部 usage（input/output/total/cached_*）映射为对外兼容形状。"""
    return {
        "prompt_tokens": usage.get("input", 0),
        "completion_tokens": usage.get("output", 0),
        "total_tokens": usage.get("total", 0),
        "cached_read_tokens": usage.get("cached_read", 0),
        "cached_write_tokens": usage.get("cached_write", 0),
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
    assistant: dict[str, str | None] | None = None,
) -> _StreamFrame | None:
    """内部 AgentEvent → 对外 SSE 帧（纯函数，便于单测）。

    思考事件独立映射为 thinking_* 帧，供前端渲染思考分区，与正文 message 帧
    （打字机）区分；路由/工具/产物等富事件在对外流中丢弃（返回 None）。
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
            status=http_status_for(event.category),
            code=event.category.value,
            message=event.message,
        )
    if isinstance(event, DoneEvent):
        metadata: dict[str, object] = {"usage": _compat_usage(event.usage)}
        if assistant is not None:
            metadata["assistant"] = assistant
        return MessageEndEvent(
            message_id=message_id,
            conversation_id=conversation_id,
            metadata=metadata,
            created_at=created_at,
        )
    return None


def _sse_frame(event: _StreamFrame) -> str:
    return f"data: {event.model_dump_json()}\n\n"


async def _run_turn_events(
    services: AppServices, session: ConversationSession, user_input: str
) -> AsyncIterator[AgentEvent]:
    """执行单轮并逐个产出事件。"""
    emitter = QueueEmitter(services.settings)
    done = anyio.Event()

    async def run_graph() -> None:
        runtime = services.get_runtime(session.conversation_id)
        try:
            await runtime.run_turn(
                session_id=session.conversation_id,
                user_input=user_input,
                emitter=emitter,
                account_id=session.account_id,
                assistant_target=session.assistant_target,
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
