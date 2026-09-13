"""来源端口的生产适配器（agent-context-plane-spec §5.1 / §11 阶段二）。

单一动机：把既有事实来源（ConversationService / FileService）适配成上下文端口，
使 ContextAssembler 只依赖抽象，适配器本身由组合根注入。

当前只提供会话适配器：历史来源仍是 query/answer 单行拍平模型（规范 §2.4），
还原出的消息没有角色级 ID，因此 `message_id` 留空、以 `source_ref` 保留来源。
"""

from __future__ import annotations

from app.application.conversation.service import ConversationService
from app.environment.context.models import ContextMessage


class ConversationContextAdapter:
    """ConversationContextPort 实现：包装 ConversationService。

    ConversationService 已按 account_id 校验会话归属（跨账号 / 不存在 →
    NotFoundError），适配器不再重复鉴权，也不缓存任何历史。
    """

    def __init__(self, service: ConversationService) -> None:
        self._service = service

    async def load_recent_messages(
        self, *, account_id: str, conversation_id: str, limit: int
    ) -> list[ContextMessage]:
        """按账号读取最近 limit 条历史，还原为带 role 的结构化消息。"""
        history = await self._service.get_history_messages(
            account_id=account_id, conversation_id=conversation_id, limit=limit
        )
        source_ref = f"conversation:{conversation_id}"
        return [
            ContextMessage(
                role=message.role,
                content=message.content or "",
                conversation_id=conversation_id,
                source_ref=source_ref,
            )
            for message in history
        ]
