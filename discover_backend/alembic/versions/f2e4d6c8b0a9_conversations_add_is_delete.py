"""conversations add is_delete

Revision ID: f2e4d6c8b0a9
Revises: ea8172ad144a
Create Date: 2026-08-27

软删除从 status 枚举剥离为独立 is_delete 布尔（SRP / §13 改动半径评审）：
业务状态 status 只保留 ACTIVE/CLOSED，删除不再覆盖业务状态（可还原）。
存量 status='deleted' 行一并迁移为 is_delete=true 并回退业务状态为 active
（原设计已覆盖业务状态、无法还原，CLOSED 全局未使用，回退 ACTIVE 安全）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2e4d6c8b0a9"
down_revision: str | None = "ea8172ad144a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default=false 兼容既有行；显式 NOT NULL 防漏写。
    op.add_column(
        "conversations",
        sa.Column("is_delete", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # 存量软删除行迁移：status='deleted' → is_delete=true，业务状态回退 active。
    op.execute(
        "UPDATE conversations SET is_delete = true, status = 'active' WHERE status = 'deleted'"
    )


def downgrade() -> None:
    # best-effort 回退：is_delete=true 行还原为 status='deleted'（原业务状态不可知）。
    op.execute("UPDATE conversations SET status = 'deleted' WHERE is_delete = true")
    op.drop_column("conversations", "is_delete")
