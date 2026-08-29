"""会话历史服务（L0，ConversationService）：对话记录唯一入口。

对话记录生命周期在此统一管理（CLAUDE.md §13 内聚）：
- resolve：空串创建 conversations 行（归属账号 + 首查标题 + 助手绑定）并返回
  ConversationSession；显式 conversation_id 校验归属（未知/跨账号/已删 → 404）
  并按 agent_id 更新绑定。创建为 best-effort（DB 降级内部消化，舱壁），读取严格。
- record_turn：回合结束把 query/answer/thinking/usage 落库（行更新 + messages 插入）。

读取方法（list/get/delete/usage）不降级——读不到数据就该报错，经中间件走统一错误响应。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Row, distinct, func, select

from app.catalog.assistant_catalog import AssistantCatalog
from app.catalog.models import AssistantTarget, TargetType
from app.config.settings import Settings
from app.db.base import local_now
from app.db.engine import Database
from app.db.models import Conversation, Message
from app.errors.base import NotFoundError
from app.llm.models import ChatMessage
from app.schemas.conversations import (
    ConversationRecord,
    ConversationSession,
    ConversationStatus,
    DailyUsageItem,
    MessageRecord,
    MessageStatus,
    TurnRecord,
    UsageAggregate,
)

logger = logging.getLogger(__name__)

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


class ConversationService:
    """对话记录服务：生命周期（resolve）+ 历史落库/读取。"""

    def __init__(self, db: Database, settings: Settings, catalog: AssistantCatalog) -> None:
        self._db = db
        self._name_max_chars = settings.conversation_name_max_chars
        self._catalog = catalog

    # ---- 对话记录生命周期 ----
    async def resolve(
        self,
        *,
        account_id: str,
        conversation_id: str,
        agent_id: str,
        query: str,
    ) -> ConversationSession:
        """解析对话记录：空串创建（归属当前账号）；显式传入则校验存在与归属。

        创建为 best-effort（DB 降级内部消化，舱壁，与 record_turn 一致）：写失败
        仍返回有效 DTO；续聊读取严格——未知/跨账号/已软删 → 404（不泄露存在性）。
        agent_id 为用户显式助手选择：非空 → 目录校验（未知 404）+ 更新绑定；
        "generic"（保留字）→ 解除专家绑定走通用对话；空 → 沿用现有绑定。
        """
        target: AssistantTarget | None = None
        if not conversation_id.strip():
            conversation_id = uuid.uuid4().hex
            if agent_id.strip():
                target = self._catalog.resolve_target(agent_id)
            try:
                await self._create_conversation(
                    conversation_id, account_id, _target_agent_id(target), query
                )
            except Exception as exc:
                logger.warning("创建会话行失败（best-effort 忽略）：%s：%r", conversation_id, exc)
        else:
            conversation_id = conversation_id.strip()
            row = await self._get_owned(account_id, conversation_id)
            if agent_id.strip():
                target = self._catalog.resolve_target(agent_id)
                await self._update_binding(conversation_id, _target_agent_id(target))
            else:
                target = _target_from_row(row)
        return ConversationSession(
            conversation_id=conversation_id, account_id=account_id, assistant_target=target
        )

    async def _create_conversation(
        self, conversation_id: str, account_id: str, agent_id: str | None, query: str
    ) -> None:
        """新建 conversations 行（标题取首查截断，绑定落 agent_id）。"""
        async with self._db.session_factory() as session:
            session.add(
                Conversation(
                    conversation_id=conversation_id,
                    from_account_id=account_id,
                    agent_id=agent_id,
                    name=_conversation_title(query, self._name_max_chars),
                    status=ConversationStatus.ACTIVE.value,
                    dialogue_count=0,  # default 是插入期默认，构造时需显式赋 0
                    is_delete=False,  # 同上：显式初始化软删除标记
                )
            )
            await session.commit()

    async def _get_owned(self, account_id: str, conversation_id: str) -> Conversation:
        """按归属校验取会话行；未知/跨账号/已软删 → 404（不泄露存在性）。"""
        async with self._db.session_factory() as session:
            row = await session.get(Conversation, conversation_id)
        if row is None or row.from_account_id != account_id or row.is_delete:
            raise NotFoundError(f"未知会话：{conversation_id}")
        return row

    async def _update_binding(self, conversation_id: str, agent_id: str | None) -> None:
        """更新会话行的助手绑定（切换同样走此方法）。"""
        async with self._db.session_factory() as session:
            row = await session.get(Conversation, conversation_id)
            if row is not None:
                row.agent_id = agent_id
                row.updated_at = local_now()
                await session.commit()

    async def record_turn(self, conversation_id: str, turn: TurnRecord) -> bool:
        """落库一回合：conversation 行更新（计数/快照）+ message 插入。

        conversation 行由 resolve 建好；此处行缺失为兜底重建（best-effort 场景
        下 resolve 未落库），name 取 turn.conversation_name 或 query 截断。
        续聊保留原 name。DB 故障仅记日志返回 False（舱壁），不阻断主流程。
        """
        try:
            async with self._db.session_factory() as session:
                convo = await session.get(Conversation, conversation_id)
                if convo is None:
                    convo = Conversation(
                        conversation_id=conversation_id,
                        from_account_id=turn.account_id,
                        name=turn.conversation_name or turn.query[:64],
                        status=ConversationStatus.ACTIVE.value,
                        dialogue_count=0,  # default 是插入期默认，构造时需显式赋 0
                        is_delete=False,  # 同上：显式初始化软删除标记
                    )
                    session.add(convo)
                convo.dialogue_count += 1
                convo.updated_at = local_now()
                if convo.agent_id is None and turn.agent_id:
                    convo.agent_id = turn.agent_id
                if convo.model_provider is None and turn.provider:
                    convo.model_provider = turn.provider
                if convo.model_id is None and turn.model:
                    convo.model_id = turn.model
                session.add(
                    Message(
                        message_id=turn.message_id,
                        conversation_id=conversation_id,
                        created_by=turn.account_id,
                        agent_id=turn.agent_id,
                        provider=turn.provider,
                        model=turn.model,
                        query=turn.query,
                        answer=turn.answer,
                        thinking=turn.thinking,
                        status=turn.status.value,
                        error=turn.error,
                        latency_ms=turn.latency_ms,
                        prompt_tokens=turn.usage.prompt_tokens,
                        completion_tokens=turn.usage.completion_tokens,
                        total_tokens=turn.usage.total_tokens,
                        cached_read_tokens=turn.usage.cached_read_tokens,
                        cached_write_tokens=turn.usage.cached_write_tokens,
                    )
                )
                await session.commit()
            return True
        except Exception as exc:
            # 预期降级（DB 未启动/不可达）：warning 即可，不必每回合刷堆栈
            logger.warning("历史落库失败（best-effort 忽略）：%s：%r", conversation_id, exc)
            return False

    async def list_conversations(
        self, account_id: str, *, limit: int, offset: int
    ) -> list[ConversationRecord]:
        """分页列出当前账号会话（按 updated_at 倒序，跨账号隔离）。"""
        async with self._db.session_factory() as session:
            rows = (
                await session.scalars(
                    select(Conversation)
                    .where(
                        Conversation.from_account_id == account_id,
                        Conversation.is_delete.is_(False),
                    )
                    .order_by(Conversation.updated_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        return [_conversation_to_record(row) for row in rows]

    async def get_messages(
        self, account_id: str, conversation_id: str, *, limit: int, offset: int
    ) -> list[MessageRecord]:
        """分页列出会话消息（按 created_at 升序）。

        先校验会话归属（from_account_id）；跨账号或不存在 → 404（不泄露存在性）。
        """
        async with self._db.session_factory() as session:
            convo = await session.get(Conversation, conversation_id)
            if convo is None or convo.from_account_id != account_id:
                raise NotFoundError(f"未知会话：{conversation_id}")
            rows = (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.asc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        return [_message_to_record(row) for row in rows]

    async def get_history_messages(
        self, account_id: str, conversation_id: str, *, limit: int
    ) -> list[ChatMessage]:
        """加载会话历史为模型上下文消息（会话记忆 L1）。

        与 get_messages 同源：先校验会话归属（跨账号/不存在 → 404），再按
        created_at 升序取**最近** limit 条（desc 取数后反转），还原为
        user(query)/assistant(answer) 消息对；thinking 为审计内容不进模型上下文
        （db/models.py 约定），错误回合 answer 为空则不产出 assistant 消息。
        """
        async with self._db.session_factory() as session:
            convo = await session.get(Conversation, conversation_id)
            if convo is None or convo.from_account_id != account_id:
                raise NotFoundError(f"未知会话：{conversation_id}")
            rows = (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.desc())
                    .limit(limit)
                )
            ).all()
        messages: list[ChatMessage] = []
        for row in reversed(rows):
            if row.query:
                messages.append(ChatMessage(role="user", content=row.query))
            if row.answer:
                messages.append(ChatMessage(role="assistant", content=row.answer))
        return messages

    async def soft_delete_conversation(self, account_id: str, conversation_id: str) -> bool:
        """软删除会话：标记 is_delete=true（行与 messages 保留，token 可审计）。

        业务状态 status 不被覆盖（可还原）；不存在、已删除或非本人账号 → False。
        显式用户操作，DB 错误照常上抛（不降级）。
        """
        async with self._db.session_factory() as session:
            convo = await session.get(Conversation, conversation_id)
            if convo is None or convo.is_delete or convo.from_account_id != account_id:
                return False
            convo.is_delete = True
            convo.updated_at = local_now()
            await session.commit()
        return True

    # ---- 账号 token 用量聚合（按 messages.created_by） ----
    async def aggregate_daily_usage(self, account_id: str, *, days: int) -> list[DailyUsageItem]:
        """近 days 天逐日用量（口径同 aggregate_user_usage；按 GMT+8 自然日分组）。

        返回 [今天 - days + 1, 今天] 每天一条、零填充、升序；窗口外消息不计。
        """
        start, lower, upper = _daily_usage_window(days)
        async with self._db.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        Message.conversation_id,
                        Message.prompt_tokens,
                        Message.completion_tokens,
                        Message.total_tokens,
                        Message.cached_read_tokens,
                        Message.cached_write_tokens,
                        Message.created_at,
                    )
                    .where(Message.created_by == account_id)
                    .where(Message.created_at >= lower)
                    .where(Message.created_at < upper)
                )
            ).all()
        return _fill_daily_items(_accumulate_daily(rows), start, days)

    async def aggregate_user_usage(self, account_id: str) -> UsageAggregate:
        """单账号用量：会话数（去重）+ 回合数 + token 合计（含缓存命中/写入）。"""
        async with self._db.session_factory() as session:
            row = (
                await session.execute(
                    select(
                        func.count(distinct(Message.conversation_id)),
                        func.count(Message.message_id),
                        func.coalesce(func.sum(Message.prompt_tokens), 0),
                        func.coalesce(func.sum(Message.completion_tokens), 0),
                        func.coalesce(func.sum(Message.total_tokens), 0),
                        func.coalesce(func.sum(Message.cached_read_tokens), 0),
                        func.coalesce(func.sum(Message.cached_write_tokens), 0),
                    ).where(Message.created_by == account_id)
                )
            ).one()
        return UsageAggregate(
            conversation_count=row[0],
            message_count=row[1],
            prompt_tokens=row[2],
            completion_tokens=row[3],
            total_tokens=row[4],
            cached_read_tokens=row[5],
            cached_write_tokens=row[6],
        )

    async def usage_by_account(self) -> dict[str, UsageAggregate]:
        """全部账号用量（超级用户接口）：按 created_by 分组聚合。"""
        async with self._db.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        Message.created_by,
                        func.count(distinct(Message.conversation_id)),
                        func.count(Message.message_id),
                        func.coalesce(func.sum(Message.prompt_tokens), 0),
                        func.coalesce(func.sum(Message.completion_tokens), 0),
                        func.coalesce(func.sum(Message.total_tokens), 0),
                        func.coalesce(func.sum(Message.cached_read_tokens), 0),
                        func.coalesce(func.sum(Message.cached_write_tokens), 0),
                    ).group_by(Message.created_by)
                )
            ).all()
        result: dict[str, UsageAggregate] = {}
        for row in rows:
            result[row[0]] = UsageAggregate(
                conversation_count=row[1],
                message_count=row[2],
                prompt_tokens=row[3],
                completion_tokens=row[4],
                total_tokens=row[5],
                cached_read_tokens=row[6],
                cached_write_tokens=row[7],
            )
        return result
