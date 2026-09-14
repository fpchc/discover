"""add agent package base bundle columns

Revision ID: f4b6d8e0a2c4
Revises: e8a1f2b3c4d5
Create Date: 2026-09-14

`e8a1f2b3c4d5` 的建表脚本遗漏了 ORM 已有的草稿底座字段。为兼容已经执行过
该版本的数据库，使用后续迁移补齐，而不是修改历史迁移。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b6d8e0a2c4"
down_revision: str | None = "e8a1f2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_packages",
        sa.Column("base_storage_key", sa.String(64), nullable=True),
    )
    op.add_column(
        "agent_packages",
        sa.Column("base_checksum", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_packages", "base_checksum")
    op.drop_column("agent_packages", "base_storage_key")