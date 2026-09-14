"""normalize agent package files into an explicit entry tree

Revision ID: b8d0f2a4c6e8
Revises: f4b6d8e0a2c4
Create Date: 2026-09-14

旧表只保存完整 path。本迁移把每个路径拆成目录节点和文件节点，
使用 parent_id + name 表达层级；目录也持久化为独立行，为空目录、
移动和可视化编辑保留稳定结构。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d0f2a4c6e8"
down_revision: str | None = "f4b6d8e0a2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("agent_package_files", "agent_package_entries")
    op.drop_index("uq_agent_package_files_package_path", table_name="agent_package_entries")
    op.drop_index("ix_agent_package_files_package_id", table_name="agent_package_entries")
    op.alter_column(
        "agent_package_entries",
        "content",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.add_column(
        "agent_package_entries",
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "agent_package_entries",
        sa.Column("entry_type", sa.String(16), nullable=True),
    )
    op.add_column(
        "agent_package_entries",
        sa.Column("name", sa.String(255), nullable=True),
    )
    op.add_column(
        "agent_package_entries",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.execute(
        sa.text(
            """
            WITH input_files AS (
                SELECT package_id, path, string_to_array(path, '/') AS parts
                FROM agent_package_entries
                WHERE content IS NOT NULL
            ),
            directory_paths AS (
                SELECT DISTINCT
                    input_files.package_id,
                    array_to_string(input_files.parts[1:depth], '/') AS path
                FROM input_files
                CROSS JOIN LATERAL generate_series(
                    1,
                    cardinality(input_files.parts) - 1
                ) AS generated(depth)
            )
            INSERT INTO agent_package_entries (
                package_id,
                path,
                content,
                parent_id,
                entry_type,
                name,
                sort_order
            )
            SELECT
                directory_paths.package_id,
                directory_paths.path,
                NULL,
                NULL,
                'directory',
                split_part(
                    directory_paths.path,
                    '/',
                    cardinality(string_to_array(directory_paths.path, '/'))
                ),
                0
            FROM directory_paths
            WHERE NOT EXISTS (
                SELECT 1
                FROM agent_package_entries existing
                WHERE existing.package_id = directory_paths.package_id
                  AND existing.path = directory_paths.path
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO agent_package_entries (
                package_id,
                path,
                content,
                parent_id,
                entry_type,
                name,
                sort_order
            )
            SELECT DISTINCT
                package_id,
                '',
                NULL::text,
                NULL::bigint,
                'directory',
                '',
                0
            FROM agent_package_entries existing
            WHERE NOT EXISTS (
                SELECT 1
                FROM agent_package_entries root
                WHERE root.package_id = existing.package_id
                  AND root.parent_id IS NULL
                  AND root.name = ''
                  AND root.entry_type = 'directory'
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_package_entries
            SET entry_type = 'file',
                name = regexp_replace(path, '^.*/', '')
            WHERE entry_type IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_package_entries AS child
            SET parent_id = parent.id
            FROM agent_package_entries AS parent
            WHERE parent.package_id = child.package_id
              AND parent.entry_type = 'directory'
              AND parent.path = regexp_replace(child.path, '/[^/]*$', '')
              AND child.path LIKE '%/%'
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE agent_package_entries AS child
            SET parent_id = root.id
            FROM agent_package_entries AS root
            WHERE root.package_id = child.package_id
              AND root.parent_id IS NULL
              AND root.name = ''
              AND root.entry_type = 'directory'
              AND child.parent_id IS NULL
              AND child.name <> ''
            """
        )
    )
    op.alter_column(
        "agent_package_entries",
        "entry_type",
        existing_type=sa.String(16),
        nullable=False,
    )
    op.alter_column(
        "agent_package_entries",
        "name",
        existing_type=sa.String(255),
        nullable=False,
    )
    op.create_check_constraint(
        "content",
        "agent_package_entries",
        "(entry_type = 'directory' AND content IS NULL) OR "
        "(entry_type = 'file' AND content IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_agent_package_entries_parent",
        "agent_package_entries",
        "agent_package_entries",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_agent_package_entries_package_id",
        "agent_package_entries",
        ["package_id"],
    )
    op.create_index(
        "uq_agent_package_entries_sibling",
        "agent_package_entries",
        ["package_id", "parent_id", "name"],
        unique=True,
    )
    op.create_index(
        "uq_agent_package_entries_root",
        "agent_package_entries",
        ["package_id"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )
    op.drop_column("agent_package_entries", "path")


def downgrade() -> None:
    op.add_column(
        "agent_package_entries",
        sa.Column("path", sa.String(512), nullable=True),
    )
    op.execute(
        sa.text(
            """
            WITH RECURSIVE entry_paths AS (
                SELECT
                    id,
                    parent_id,
                    name,
                    ''::text AS path
                FROM agent_package_entries
                WHERE parent_id IS NULL

                UNION ALL

                SELECT
                    child.id,
                    child.parent_id,
                    child.name,
                    CASE
                        WHEN parent.path = '' THEN child.name
                        ELSE parent.path || '/' || child.name
                    END
                FROM agent_package_entries AS child
                JOIN entry_paths AS parent ON child.parent_id = parent.id
            )
            UPDATE agent_package_entries AS entry
            SET path = entry_paths.path
            FROM entry_paths
            WHERE entry.id = entry_paths.id
            """
        )
    )
    op.drop_constraint(
        "content",
        "agent_package_entries",
        type_="check",
    )
    op.drop_constraint(
        "fk_agent_package_entries_parent",
        "agent_package_entries",
        type_="foreignkey",
    )
    op.drop_index("uq_agent_package_entries_root", table_name="agent_package_entries")
    op.drop_index("uq_agent_package_entries_sibling", table_name="agent_package_entries")
    op.drop_index("ix_agent_package_entries_package_id", table_name="agent_package_entries")
    op.execute(sa.text("DELETE FROM agent_package_entries WHERE entry_type = 'directory'"))
    op.alter_column(
        "agent_package_entries",
        "content",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.drop_column("agent_package_entries", "sort_order")
    op.drop_column("agent_package_entries", "name")
    op.drop_column("agent_package_entries", "entry_type")
    op.drop_column("agent_package_entries", "parent_id")
    op.alter_column(
        "agent_package_entries",
        "path",
        existing_type=sa.String(512),
        nullable=False,
    )
    op.rename_table("agent_package_entries", "agent_package_files")
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
