"""run action checkpoint

Revision ID: a3c4d5e6f7a8
Revises: f8a1b2c3d4e5
Create Date: 2026-09-15 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c4d5e6f7a8"
down_revision: str | None = "f8a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_action_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("action_id", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("arguments_json", sa.Text(), nullable=False),
        sa.Column("arguments_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("side_effect_class", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_action_records")),
        sa.UniqueConstraint("run_id", "action_id", name="uq_run_action_records_run_action"),
    )
    op.create_index(
        op.f("ix_run_action_records_run_id"), "run_action_records", ["run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_run_action_records_run_id"), table_name="run_action_records")
    op.drop_table("run_action_records")
