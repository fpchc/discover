"""会话历史（ConversationService）：conversations / messages 落库与读取的唯一入口。

跨边界 DTO 一律 pydantic（CLAUDE.md §3），见 models；持久化载体为 ORM。
"""

from app.conversations.models import (
    ConversationRecord,
    ConversationStatus,
    MessageRecord,
    MessageStatus,
    TurnRecord,
    TurnUsage,
)
from app.conversations.service import ConversationService

__all__ = [
    "ConversationRecord",
    "ConversationService",
    "ConversationStatus",
    "MessageRecord",
    "MessageStatus",
    "TurnRecord",
    "TurnUsage",
]
