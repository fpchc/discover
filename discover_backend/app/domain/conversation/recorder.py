"""回合事件聚合器：RunEvent 流 → TurnRecord 落库载荷。

单一动机：把「单回合内的事件聚合」从接入层下沉到领域层（CLAUDE.md §13 内聚），
路由只做参数提取与转调。聚合结果经 ConversationService.record_turn 落库，
本模块不感知存储后端（DIP）。

状态推导（§17.1）：TurnRecord.status 由 Run 终态事件显式映射，不根据是否
收到 ErrorEvent 推断；客户端中断（无终态事件）由 exit_reason 兜底。
"""

from __future__ import annotations

from typing import Literal

from app.interfaces.schemas.conversations import (
    ConversationSession,
    MessageStatus,
    TurnRecord,
    TurnUsage,
)
from app.runtime.events.run_events import (
    LLMCallStarted,
    LLMUsageUpdated,
    RunCancelled,
    RunCompleted,
    RunEvent,
    RunFailed,
    TextDelta,
    ThinkingDelta,
    ThinkingEnded,
)
from app.shared.errors.base import ErrorCategory

# 回合退出终止原因：normal 正常走完 / interrupted 客户端中断 / error 服务端异常。
# 与 MessageStatus 对应，供 finally 兜底落库时统一推导状态。
ExitReason = Literal["normal", "interrupted", "error"]


def resolve_turn_status(exit_reason: ExitReason, error: str | None) -> MessageStatus:
    """落库状态推导：RunFailed / 服务端异常 → error；客户端中断 → interrupted。

    优先级 error 高于 interrupted（服务端失败优先如实标记），正常路径 →
    normal。供路由 finally 兜底落库时调用。
    """
    if error is not None or exit_reason == "error":
        return MessageStatus.ERROR
    if exit_reason == "interrupted":
        return MessageStatus.INTERRUPTED
    return MessageStatus.NORMAL


class TurnRecorder:
    """单回合事件收集：聚合正文/思考/usage/provider/model/error，供落库。

    # pragma: 简化 — 回合内部事件收集器，不跨边界序列化，无需 pydantic
    """

    def __init__(
        self,
        *,
        message_id: str,
        query: str,
        session: ConversationSession,
    ) -> None:
        self._message_id = message_id
        self._query = query
        self._session = session
        self._text_parts: list[str] = []
        self._thinking_parts: list[str] = []
        self._usage: dict[str, int] = {}
        self._provider: str | None = None
        self._model: str | None = None
        self._duration_ms: int = 0
        self._error: str | None = None
        self._error_category: ErrorCategory | None = None
        self._recoverable: bool = False
        self._status: MessageStatus | None = None

    @property
    def answer(self) -> str:
        """已聚合正文（供 SSE 退出日志 / blocking 响应使用）。"""
        return "".join(self._text_parts)

    @property
    def thinking(self) -> str:
        """已聚合思考正文（供 SSE 退出日志使用）。"""
        return "".join(self._thinking_parts)

    @property
    def error(self) -> str | None:
        """RunFailed 携带的错误消息（无失败 → None）。"""
        return self._error

    @property
    def error_category(self) -> ErrorCategory | None:
        """RunFailed 携带的错误分类（无失败 → None）。"""
        return self._error_category

    @property
    def recoverable(self) -> bool:
        """RunFailed 携带的可恢复标记。"""
        return self._recoverable

    def absorb(self, event: RunEvent) -> None:
        """吸收一个 RunEvent，更新回合聚合态。"""
        if isinstance(event, TextDelta):
            self._text_parts.append(event.text)
        elif isinstance(event, ThinkingDelta):
            self._thinking_parts.append(event.text)
        elif isinstance(event, ThinkingEnded):
            self._duration_ms = event.duration_ms
        elif isinstance(event, LLMUsageUpdated):
            self._merge_usage(event.usage)
        elif isinstance(event, LLMCallStarted):
            self._provider = event.provider or self._provider
            self._model = event.model or self._model
        elif isinstance(event, RunCompleted):
            self._status = MessageStatus.NORMAL
            self._duration_ms = (
                int(event.budget_snapshot.usage.duration_seconds * 1000)
                if event.budget_snapshot is not None
                else self._duration_ms
            )
        elif isinstance(event, RunFailed):
            self._status = MessageStatus.ERROR
            self._error = event.message or self._error
            self._error_category = event.error_category or self._error_category
            self._recoverable = event.recoverable
        elif isinstance(event, RunCancelled):
            self._status = MessageStatus.INTERRUPTED
            self._error = event.message or self._error

    def compat_usage(self) -> dict[str, int]:
        """对外兼容 5 键用量形状（message_end metadata / blocking 响应）。"""
        return {
            "prompt_tokens": self._usage.get("input", 0),
            "completion_tokens": self._usage.get("output", 0),
            "total_tokens": self._usage.get("total", 0),
            "cached_read_tokens": self._usage.get("cached_read", 0),
            "cached_write_tokens": self._usage.get("cached_write", 0),
        }

    def merge(self, text: str | None = None, thinking: str | None = None) -> None:
        """追加正文/思考增量（供非事件通道的直推文本聚合）。"""
        if text:
            self._text_parts.append(text)
        if thinking:
            self._thinking_parts.append(thinking)

    def build(
        self,
        *,
        exit_reason: ExitReason = "normal",
        fallback_status: MessageStatus | None = None,
        conversation_name: str = "",
    ) -> TurnRecord:
        """产出 TurnRecord：状态优先取 Run 终态推导，缺失时按 exit_reason 兜底。"""
        status = self._status
        if status is None:
            status = fallback_status or resolve_turn_status(exit_reason, self._error)
        return TurnRecord(
            message_id=self._message_id,
            query=self._query,
            answer="".join(self._text_parts) or None,
            thinking="".join(self._thinking_parts) or None,
            status=status,
            error=self._error,
            agent_id=self._session.agent_id_label,
            provider=self._provider,
            model=self._model,
            latency_ms=self._duration_ms,
            usage=TurnUsage(
                prompt_tokens=self._usage.get("input", 0),
                completion_tokens=self._usage.get("output", 0),
                total_tokens=self._usage.get("total", 0),
                cached_read_tokens=self._usage.get("cached_read", 0),
                cached_write_tokens=self._usage.get("cached_write", 0),
            ),
            conversation_name=conversation_name,
            account_id=self._session.account_id,
        )

    def _merge_usage(self, usage: dict[str, int]) -> None:
        """把单次用量累加进回合统计（缺省键按 0 计，就地更新）。"""
        for key in ("input", "output", "total", "cached_read", "cached_write"):
            self._usage[key] = self._usage.get(key, 0) + usage.get(key, 0)
