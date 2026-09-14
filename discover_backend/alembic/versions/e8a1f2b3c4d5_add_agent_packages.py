"""add agent_packages / agent_package_files

Revision ID: e8a1f2b3c4d5
Revises: 1a2b3c4d5e6f
Create Date: 2026-09-13

技能包管理（管理员在线修改/调试）：
- agent_packages：一次发布一个 agent 级版本化 bundle（字节在存储层）。
- agent_package_files：可编辑文件（AGENT/SKILL 正文、references、templates）。
- 脚本与 schemas 仍由代码发布，不入库（发布时从代码包拷入 bundle）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "e8a1f2b3c4d5"
down_revision: str | None = "1a2b3c4d5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_packages",
        sa.Column("package_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_key", sa.String(64), nullable=True),
        sa.Column("checksum", sa.String(128), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agent_packages_agent_status",
        "agent_packages",
        ["agent_id", "status"],
    )
    op.create_index(
        "uq_agent_packages_agent_version_status",
        "agent_packages",
        ["agent_id", "version", "status"],
        unique=True,
    )
    op.create_table(
        "agent_package_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("package_id", UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_agent_package_files_package_id",
        "agent_package_files",
        ["package_id"],
    )
    op.create_index(
        "uq_agent_package_files_package_path",
        "agent_package_files",
        ["package_id", "path"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_agent_package_files_package_path", table_name="agent_package_files")
    op.drop_index("ix_agent_package_files_package_id", table_name="agent_package_files")
    op.drop_table("agent_package_files")
    op.drop_index("uq_agent_packages_agent_version_status", table_name="agent_packages")
    op.drop_index("ix_agent_packages_agent_status", table_name="agent_packages")
    op.drop_table("agent_packages")
