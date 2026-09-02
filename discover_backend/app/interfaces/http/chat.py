"""对话接口（L4）：POST /chat-messages + POST /chat-messages/{id}/stop。

请求体 `{query, response_mode, conversation_id, ...}`；`conversation_id` 空串
自动创建会话（对话记录由 ConversationService.resolve 建行并归属当前账号），
续聊带上即复用（归属校验 404）。`streaming` 走 SSE（`data:` 帧，`event` 判别：
message / message_end / ping / error，以 message_end 收尾，无 [DONE]）；
`blocking` 返回 chat-messages JSON。图执行与 SSE 写循环在同一任务组：
客户端断开即取消图执行并释放会话资源（异常路径亦然）。

stop 接口显式取消进行中回合：回合在路由层登记 ActiveTurn（同会话并发二次发起
→ 409，见 ActiveTurnRegistry），stop 经 task.cancel() 中断——与客户端断开同一
取消原语，统一落入 interrupted 落库。

对话记录生命周期（创建/归属/绑定/标题）全部由 ConversationService 管理，
路由只做参数提取与转调（CLAUDE.md §13 内聚/耦合）；历史落库回合结束统一调
`record_turn`（正常 / error / 客户端中断皆记录，中断回合保留 partial 内容），
DB 降级由服务内部消化，路由无 try/except。
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

import anyio
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.bootstrap.container import AppServices, get_services
from app.interfaces.http.deps import get_current_account_id
from app.interfaces.schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatStopResponse,
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
from app.runtime.events.emitter import QueueEmitter
from app.runtime.events.events import (
    AgentEvent,
    DoneEvent,
    ErrorEvent,
    HeartbeatEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ThinkingEndedEvent,
    ThinkingStartedEvent,
)
from app.runtime.turn import ActiveTurn
from app.shared.errors.base import ConflictError, ErrorCategory, PlatformError, http_status_for
from app.shared.utils.sanitize import sanitize_error_message

router = APIRouter(tags=["chat"])

logger = logging.getLogger(__name__)

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


# 回合退出终止原因：normal 正常走完 / interrupted 客户端中断 / error 服务端异常。
# 与 MessageStatus 对应，供 finally 兜底落库时统一推导状态。
_ExitReason = Literal["normal", "interrupted", "error"]


def _resolve_status(exit_reason: _ExitReason, error: ErrorEvent | None) -> MessageStatus:
    """落库状态推导：ErrorEvent 或服务端异常 → error；客户端中断 → interrupted。

    优先级 error 高于 interrupted（服务端失败优先如实标记），正常路径 →
    normal。供 _blocking / _stream_sse 在 finally 兜底落库时调用。
    """
    if error is not None or exit_reason == "error":
        return MessageStatus.ERROR
    if exit_reason == "interrupted":
        return MessageStatus.INTERRUPTED
    return MessageStatus.NORMAL


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
    """停止会话的进行中回合：task.cancel()（与客户端断连同一取消原语）。

    归属校验走严格读（未知 / 跨账号 / 已软删 → 404，不泄露存在性）；无进行中
    回合返回 idle。stopping 只承诺取消已请求，前端以 SSE 流关闭为准。
    """
    assert services.conversation_service is not None
    await services.conversation_service.require_owned(account_id, conversation_id)
    turn = services.active_turns.request_stop(conversation_id)
    if turn is None:
        return ChatStopResponse(conversation_id=conversation_id, status="idle")
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
    """blocking：聚合正文增量，返回 chat-messages JSON。

    turn.task 捕获当前请求任务供 stop 取消；预启动窗口的 stop（stop_requested）
    在启动时立即中断。取消/异常路径先落库后注销（与 _stream_sse 一致的顺序）。
    """
    collector = _TurnCollector()
    exit_reason: _ExitReason = "normal"
    turn.task = asyncio.current_task()
    try:
        if turn.stop_requested:
            raise asyncio.CancelledError
        async for event in _run_turn_events(services, session, user_input):
            collector.absorb(event)
    except asyncio.CancelledError:
        # 客户端断开 / 服务端 stop：聚合的部分内容照常落库（interrupted），再向外传播取消
        exit_reason = "interrupted"
        raise
    except Exception:
        exit_reason = "error"
        raise
    finally:
        await _persist_turn(
            services,
            session,
            message_id,
            user_input,
            collector,
            status=_resolve_status(exit_reason, collector.error),
        )
        services.active_turns.unregister(session.conversation_id, turn)
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
    turn: ActiveTurn,
) -> AsyncIterator[str]:
    """流式：内部事件转 `event` 判别帧，以 message_end 收尾；流尾落库。

    日志观测：记录流生命周期与终止原因（正常走完 / 生成器关闭 / 任务取消 /
    异常）。所有退出路径（正常 / 客户端中断 / 服务端异常）都兜底落库一次，
    中断回合保留 query + partial 内容，供历史可查。

    turn.task 捕获真正承载生成的任务（供 stop 跨任务取消）；先置 task 再查
    stop_requested，保证预启动 stop 不落空。服务端 stop 与客户端断连共用同一
    取消原语（task.cancel()），统一落入 except(GeneratorExit, CancelledError)。
    """
    collector = _TurnCollector()
    assistant = session.assistant_meta
    exit_reason: _ExitReason = "normal"
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
        await _persist_turn(
            services,
            session,
            message_id,
            user_input,
            collector,
            status=_resolve_status(exit_reason, collector.error),
        )
        services.active_turns.unregister(session.conversation_id, turn)
        text = "".join(collector.text_parts)
        thinking = "".join(collector.thinking_parts)
        logger.info(
            "SSE 流退出",
            extra={
                "message_id": message_id,
                "conversation_id": session.conversation_id,
                "exit_reason": exit_reason,
                "text_len": len(text),
                "thinking_len": len(thinking),
                "has_error": collector.error is not None,
            },
        )


async def _persist_turn(
    services: AppServices,
    session: ConversationSession,
    message_id: str,
    user_input: str,
    collector: _TurnCollector,
    *,
    status: MessageStatus,
) -> None:
    """回合结束落库一次；DB 降级由服务内部消化（路由无感知）。

    status 由调用方按终止原因推导（_resolve_status）；中断回合同样落库，
    记录 query + partial 内容。
    """
    if services.conversation_service is None:
        return
    turn = TurnRecord(
        message_id=message_id,
        query=user_input,
        answer="".join(collector.text_parts) or None,
        thinking="".join(collector.thinking_parts) or None,
        status=status,
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
    # 中断/异常路径在取消传播途中落库：anyio 取消 scope 语义下，取消请求后
    # 任何 checkpoint 会再次收到 CancelledError，DB 写入会被打断；shield 保护
    # 写入完成（best-effort），随后取消继续向外传播。
    with anyio.CancelScope(shield=True):
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
        logger.info("图执行开始", extra={"conversation_id": session.conversation_id})
        try:
            await runtime.run_turn(
                session_id=session.conversation_id,
                user_input=user_input,
                emitter=emitter,
                account_id=session.account_id,
                assistant_target=session.assistant_target,
            )
            logger.info("图执行正常完成", extra={"conversation_id": session.conversation_id})
        except PlatformError as exc:
            logger.warning(
                "图执行领域异常：%s：%s",
                exc.category.value,
                sanitize_error_message(
                    str(exc), max_length=services.settings.error_message_max_chars
                ),
                extra={"conversation_id": session.conversation_id},
            )
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
            logger.exception(
                "图执行未捕获异常",
                extra={"conversation_id": session.conversation_id},
            )
            await emitter.emit(
                ErrorEvent(
                    category=ErrorCategory.SERVER,
                    message="内部错误",
                    recoverable=False,
                    suggestion="请重试",
                )
            )
        finally:
            logger.info(
                "图执行收尾（finish+done）",
                extra={"conversation_id": session.conversation_id},
            )
            await emitter.finish()
            done.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(emitter.run)
        tg.start_soon(run_graph)
        while True:
            event = await _next_event(emitter, done)
            if event is None:
                logger.info("事件流自然结束", extra={"conversation_id": session.conversation_id})
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
        except Exception:
            logger.exception("事件队列读取异常", extra={"done": done.is_set()})
            raise
