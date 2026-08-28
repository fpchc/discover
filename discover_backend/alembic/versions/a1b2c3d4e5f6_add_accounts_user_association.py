"""accounts 账号表 + 既有表用户关联列

Revision ID: a1b2c3d4e5f6
Revises: f2e4d6c8b0a9
Create Date: 2026-08-28

说明：账号表按用户 DDL（id uuid + gen_random_uuid 默认值、phone 索引、
username 唯一索引、is_system 标注超级用户）。原 DDL 的 uuid_generate_v4() 依赖
pgcrypto 扩展，托管 PG 常无权限创建（实测 UndefinedFunctionError），改用
PostgreSQL 13+ 内置 gen_random_uuid()，无需任何扩展。既有 conversations /
messages / upload_files / dedup_clues 加 from_account_id / created_by 关联列
（varchar(36) 存 uuid 文本），回填系统遗留账号；dedup_clues 主键改
(created_by, clue_id) 组合键并按账号隔离去重历史。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f2e4d6c8b0a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 系统遗留账号（回填既有数据归属；与 app/db/models.py SYSTEM_ACCOUNT_ID 对齐）
SYSTEM_ACCOUNT_UUID = "00000000-0000-0000-0000-000000000001"


def _backfill(table: str, column: str) -> None:
    """新增列回填为系统遗留账号（先加可空列 → 回填 → 置 NOT NULL）。

    op.execute 在离线模式不接受绑定参数；值均为固定常量（无注入风险），
    直接内联字面量以便 --sql 生成。
    """
    op.add_column(table, sa.Column(column, sa.String(length=36), nullable=True))
    op.execute(f"UPDATE {table} SET {column} = '{SYSTEM_ACCOUNT_UUID}' WHERE {column} IS NULL")
    op.alter_column(table, column, nullable=False)
    op.create_index(f"ix_{table}_{column}", table, [column], unique=False)


def upgrade() -> None:
    # ---- accounts 表（用户 DDL 2026-08-28；默认值改用 PG13+ 内置 gen_random_uuid，
    #      不依赖 pgcrypto 扩展，托管 PG 无需扩展权限） ----
    op.create_table(
        "accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("avatar", sa.String(length=255), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("last_login_ip", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column("initialized_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
        ),
        sa.Column("username", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("account_phone_idx", "accounts", ["phone"], unique=False)
    op.create_index("accounts_username_index", "accounts", ["username"], unique=True)

    # 系统遗留账号（固定 uuid、is_system=true；无密码不可登录，仅作归属回填）
    op.execute(
        "INSERT INTO accounts (id, name, phone, username, is_system, password_hash) "
        f"VALUES ('{SYSTEM_ACCOUNT_UUID}', '系统账号', 'system', 'system', true, NULL) "
        "ON CONFLICT (id) DO NOTHING"
    )

    # ---- 既有表用户关联列（回填系统遗留账号） ----
    _backfill("conversations", "from_account_id")
    _backfill("messages", "created_by")
    _backfill("upload_files", "created_by")

    # dedup_clues：加列回填 → 消除同日同产品 clue_id 冲突（保留最新 created_at）→ 组合主键
    op.add_column("dedup_clues", sa.Column("created_by", sa.String(length=36), nullable=True))
    op.execute(
        f"UPDATE dedup_clues SET created_by = '{SYSTEM_ACCOUNT_UUID}' WHERE created_by IS NULL"
    )
    op.execute(
        sa.text(
            "DELETE FROM dedup_clues a USING dedup_clues b "
            "WHERE a.clue_id = b.clue_id AND a.created_at < b.created_at"
        )
    )
    op.alter_column("dedup_clues", "created_by", nullable=False)
    op.create_index("ix_dedup_clues_created_by", "dedup_clues", ["created_by"], unique=False)
    op.drop_constraint("pk_dedup_clues", "dedup_clues", type_="primary")
    op.create_primary_key("pk_dedup_clues", "dedup_clues", ["created_by", "clue_id"])


def downgrade() -> None:
    op.drop_constraint("pk_dedup_clues", "dedup_clues", type_="primary")
    op.create_primary_key("pk_dedup_clues", "dedup_clues", ["clue_id"])
    op.drop_index("ix_dedup_clues_created_by", table_name="dedup_clues")
    op.drop_column("dedup_clues", "created_by")

    op.drop_index("ix_upload_files_created_by", table_name="upload_files")
    op.drop_column("upload_files", "created_by")
    op.drop_index("ix_messages_created_by", table_name="messages")
    op.drop_column("messages", "created_by")
    op.drop_index("ix_conversations_from_account_id", table_name="conversations")
    op.drop_column("conversations", "from_account_id")

    op.drop_index("accounts_username_index", table_name="accounts")
    op.drop_index("account_phone_idx", table_name="accounts")
    op.drop_table("accounts")
