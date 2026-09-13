"""会话 ORM 行与读取 DTO 的映射、用量聚合纯函数（ConversationService 的读侧辅助）。

单一动机：把「SQL 结果 → DTO / 按日聚合」这类纯函数从服务类里拆出，避免
ConversationService 超行（AGENTS.md §5）。只依赖 DTO 与 ORM 模型，无 DB 会话。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Row

from app.application.dto.conversations import (
    ConversationRecord,
    ConversationStatus,
    DailyUsageItem,
    MessageRecord,
    MessageStatus,
)
from app.harness.targets import AssistantTarget, TargetType
from app.infrastructure.database.models import Conversation, Message

# 用量统计按 GMT+8 自然日归组：created_at 由 local_now() 记录为 GMT+8 墙钟时间，
# 其日历日即自然日（趋势图日期轴按北京时区理解）。
_USAGE_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class _DailyAccumulator:  # pragma: 简化 — 内部可变聚合累计器，跨边界 DTO 仍用 pydantic
    """单日用量累计器（纯内部聚合态；跨边界 DTO 仍用 pydantic DailyUsageItem）。"""

    conversation_ids: set[str] = field(default_factory=set)
    message_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_read_tokens: int = 0
    cached_write_tokens: int = 0

    def add(
        self,
        conversation_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cached_read_tokens: int,
        cached_write_tokens: int,
    ) -> None:
        self.conversation_ids.add(conversation_id)
        self.message_count += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.cached_read_tokens += cached_read_tokens
        self.cached_write_tokens += cached_write_tokens


def _daily_usage_window(days: int) -> tuple[date, datetime, datetime]:
    """近 days 天的墙钟窗口 [start 日 00:00, 今天+1 日 00:00)（GMT+8）。

    下限含、上限排他；以墙钟边界过滤，与库内 created_at 的墙钟语义对齐。
    """
    today = datetime.now(_USAGE_TZ).date()
    start = today - timedelta(days=days - 1)
    lower = datetime.combine(start, time.min)
    upper = datetime.combine(today + timedelta(days=1), time.min)
    return start, lower, upper


def _accumulate_daily(rows: Sequence[Row[Any]]) -> dict[date, _DailyAccumulator]:
    """窗口内消息按 GMT+8 自然日归组求和（会话数去重）。

    created_at 以墙钟日历日归组：库内即 GMT+8 墙钟（local_now()），
    不因存储 tz 标注做偏移转换。
    """
    accs: dict[date, _DailyAccumulator] = {}
    for row in rows:
        acc = accs.setdefault(row[6].date(), _DailyAccumulator())
        acc.add(row[0], row[1], row[2], row[3], row[4], row[5])
    return accs


def _fill_daily_items(
    accs: dict[date, _DailyAccumulator],
    start: date,
    days: int,
) -> list[DailyUsageItem]:
    """从 start 起逐日零填充为升序序列（无数据日为 0）。"""
    items: list[DailyUsageItem] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        acc = accs.get(day)
        items.append(
            DailyUsageItem(
                date=day,
                conversation_count=len(acc.conversation_ids) if acc else 0,
                message_count=acc.message_count if acc else 0,
                prompt_tokens=acc.prompt_tokens if acc else 0,
                completion_tokens=acc.completion_tokens if acc else 0,
                total_tokens=acc.total_tokens if acc else 0,
                cached_read_tokens=acc.cached_read_tokens if acc else 0,
                cached_write_tokens=acc.cached_write_tokens if acc else 0,
            )
        )
    return items


def _conversation_to_record(row: Conversation) -> ConversationRecord:
    return ConversationRecord(
        conversation_id=row.conversation_id,
        agent_id=row.agent_id,
        model_provider=row.model_provider,
        model_id=row.model_id,
        name=row.name,
        summary=row.summary,
        status=ConversationStatus(row.status),
        dialogue_count=row.dialogue_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _conversation_title(query: str, max_chars: int) -> str:
    """会话标题：首回合取首条 query 截断（续聊保留原 name 不覆盖）。"""
    title = query.strip().replace("\n", " ")
    if len(title) <= max_chars:
        return title
    cut = title[:max_chars]
    # 避免截断在代理对中间（emoji 等），丢弃半个字符
    if cut and 0xD800 <= ord(cut[-1]) <= 0xDBFF:
        cut = cut[:-1]
    return cut


def _target_agent_id(target: AssistantTarget | None) -> str | None:
    """AssistantTarget → conversations.agent_id：expert 取 id；其余（通用/未绑定）None。"""
    if target is None or target.type != TargetType.EXPERT:
        return None
    return target.id


def _target_from_row(row: Conversation) -> AssistantTarget | None:
    """conversations.agent_id → AssistantTarget：非空即专家绑定；空 → 未绑定。"""
    if row.agent_id:
        return AssistantTarget(type=TargetType.EXPERT, id=row.agent_id)
    return None


def _message_to_record(row: Message) -> MessageRecord:
    """ORM Message → 读取 DTO：只映射业务可见字段，不下发 token 用量与模型信息。"""
    return MessageRecord(
        message_id=row.message_id,
        conversation_id=row.conversation_id,
        agent_id=row.agent_id,
        query=row.query,
        answer=row.answer,
        thinking=row.thinking,
        status=MessageStatus(row.status),
        error=row.error,
        latency_ms=row.latency_ms,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
