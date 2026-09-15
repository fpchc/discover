"""run snapshots and run events

Revision ID: f8a1b2c3d4e5
Revises: c9e1f3a5b7d9
Create Date: 2026-09-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f8a1b2c3d4e5"
down_revision: str | None = "c9e1f3a5b7d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_snapshots",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_run_snapshots")),
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_events")),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
    )
    op.create_index(op.f("ix_run_events_run_id"), "run_events", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_run_events_run_id"), table_name="run_events")
    op.drop_table("run_events")
    op.drop_table("run_snapshots")
