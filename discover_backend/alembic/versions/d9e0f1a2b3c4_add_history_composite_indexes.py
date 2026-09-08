"""历史查询复合索引：conversations / messages 高频检索提速

Revision ID: d9e0f1a2b3c4
Revises: c7d8e9f0a1b2
Create Date: 2026-09-07

说明：连接池修复后（远程库下复用连接）查询仍受「过滤列 + 排序列」无复合索引
影响——get_messages / get_history_messages 按 conversation_id 过滤 + created_at
排序，list_conversations 按 from_account_id + is_delete 过滤 + updated_at 倒序；
补两个复合索引消除逐次排序/回表，历史记录可见性进一步提速。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_account_updated",
        "conversations",
        ["from_account_id", "is_delete", "updated_at"],
    )
    op.create_index(
        "ix_messages_conversation_created_at",
        "messages",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_created_at", table_name="messages")
    op.drop_index("ix_conversations_account_updated", table_name="conversations")
