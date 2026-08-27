"""会话历史服务（L0，ConversationService）。

对话历史持久化：record_turn 在回合结束把 query/answer/thinking/usage 落库
（conversations 行 upsert + messages 行插入）。DB 降级全部内部消化（舱壁，
评审采纳）：接口对外永远成功语义（bool），路由无需感知 DB 死活；读取方法不
降级——读不到数据就该报错，经中间件走统一错误响应。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.conversations.models import (
    ConversationRecord,
    ConversationStatus,
    MessageRecord,
    MessageStatus,
    TurnRecord,
)
from app.db.base import local_now
from app.db.engine import Database
from app.db.models import Conversation, Message

logger = logging.getLogger(__name__)


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


def _message_to_record(row: Message) -> MessageRecord:
    return MessageRecord(
        message_id=row.message_id,
        conversation_id=row.conversation_id,
        agent_id=row.agent_id,
        provider=row.provider,
        model=row.model,
        query=row.query,
        answer=row.answer,
        thinking=row.thinking,
        status=MessageStatus(row.status),
        error=row.error,
        latency_ms=row.latency_ms,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        cached_read_tokens=row.cached_read_tokens,
        cached_write_tokens=row.cached_write_tokens,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ConversationService:
    """历史记录仓库：会话/回合落库 + 读取。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_turn(self, conversation_id: str, turn: TurnRecord) -> bool:
        """落库一回合：conversation upsert + message 插入。

        conversation 行缺失则新建（首回合，name 取 turn.conversation_name），
        续聊保留原 name。DB 故障仅记日志返回 False（舱壁），不阻断主流程。
        """
        try:
            async with self._db.session_factory() as session:
                convo = await session.get(Conversation, conversation_id)
                if convo is None:
                    convo = Conversation(
                        conversation_id=conversation_id,
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

    async def list_conversations(self, *, limit: int, offset: int) -> list[ConversationRecord]:
        """分页列出会话（按 updated_at 倒序）。"""
        async with self._db.session_factory() as session:
            rows = (
                await session.scalars(
                    select(Conversation)
                    .where(Conversation.is_delete.is_(False))
                    .order_by(Conversation.updated_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        return [_conversation_to_record(row) for row in rows]

    async def get_messages(
        self, conversation_id: str, *, limit: int, offset: int
    ) -> list[MessageRecord]:
        """分页列出会话消息（按 created_at 升序）。"""
        async with self._db.session_factory() as session:
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

    async def get_usage(self, conversation_id: str) -> dict[str, object]:
        """会话级用量汇总（tokens 聚合 + 消息数，供控制台统计）。"""
        async with self._db.session_factory() as session:
            one = (
                await session.execute(
                    select(
                        func.count(Message.message_id).label("message_count"),
                        func.coalesce(func.sum(Message.prompt_tokens), 0).label("prompt_tokens"),
                        func.coalesce(func.sum(Message.completion_tokens), 0).label(
                            "completion_tokens"
                        ),
                        func.coalesce(func.sum(Message.total_tokens), 0).label("total_tokens"),
                        func.coalesce(func.sum(Message.cached_read_tokens), 0).label(
                            "cached_read_tokens"
                        ),
                        func.coalesce(func.sum(Message.cached_write_tokens), 0).label(
                            "cached_write_tokens"
                        ),
                    ).where(Message.conversation_id == conversation_id)
                )
            ).one()
        return {
            "message_count": int(one.message_count),
            "prompt_tokens": int(one.prompt_tokens),
            "completion_tokens": int(one.completion_tokens),
            "total_tokens": int(one.total_tokens),
            "cached_read_tokens": int(one.cached_read_tokens),
            "cached_write_tokens": int(one.cached_write_tokens),
        }

    async def soft_delete_conversation(self, conversation_id: str) -> bool:
        """软删除会话：标记 is_delete=true（行与 messages 保留，token 可审计）。

        业务状态 status 不被覆盖（可还原）；已删除或不存在返回 False。显式用户
        操作，DB 错误照常上抛（不降级）。
        """
        async with self._db.session_factory() as session:
            convo = await session.get(Conversation, conversation_id)
            if convo is None or convo.is_delete:
                return False
            convo.is_delete = True
            convo.updated_at = local_now()
            await session.commit()
        return True
