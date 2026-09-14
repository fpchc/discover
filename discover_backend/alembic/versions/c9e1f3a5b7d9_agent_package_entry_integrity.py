"""enforce agent package entry ownership and same-package parentage

Revision ID: c9e1f3a5b7d9
Revises: b8d0f2a4c6e8
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9e1f3a5b7d9"
down_revision: str | None = "b8d0f2a4c6e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_package_entries_package_node",
        "agent_package_entries",
        ["package_id", "id"],
    )
    op.create_foreign_key(
        "fk_agent_package_entries_package_id",
        "agent_package_entries",
        "agent_packages",
        ["package_id"],
        ["package_id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_agent_package_entries_parent",
        "agent_package_entries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_agent_package_entries_parent",
        "agent_package_entries",
        "agent_package_entries",
        ["package_id", "parent_id"],
        ["package_id", "id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_agent_package_entries_parent",
        "agent_package_entries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_agent_package_entries_parent",
        "agent_package_entries",
        "agent_package_entries",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_agent_package_entries_package_id",
        "agent_package_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_agent_package_entries_package_node",
        "agent_package_entries",
        type_="unique",
    )
