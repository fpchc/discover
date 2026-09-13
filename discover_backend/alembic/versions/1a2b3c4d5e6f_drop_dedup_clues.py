"""drop dedup_clues

Revision ID: 1a2b3c4d5e6f
Revises: d9e0f1a2b3c4
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1a2b3c4d5e6f"
down_revision: str | None = "d9e0f1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("dedup_clues")


def downgrade() -> None:
    op.create_table(
        "dedup_clues",
        sa.Column("created_by", sa.String(length=64), primary_key=True, index=True),
        sa.Column("clue_id", sa.String(length=128), primary_key=True),
        sa.Column("product_keywords", sa.JSON(), nullable=False),
        sa.Column("target_industry", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_path", sa.Text(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("excluded_companies", sa.JSON(), nullable=False),
        sa.Column("total_found", sa.Integer(), nullable=False),
        sa.Column("remaining_pool", sa.Integer(), nullable=False),
    )
