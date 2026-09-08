"""统一认证接管：accounts 新增 auth_user_id + 数据隔离列拓宽为 varchar(64)

Revision ID: c7d8e9f0a1b2
Revises: b2c3d4e5f6a7
Create Date: 2026-09-05

说明：接入统一认证平台后，用户标识为平台 user_id（JWT sub，字符串），直接作
数据隔离列（from_account_id / created_by）的值（原为本地 uuid 文本，varchar(36)）。

- `accounts.auth_user_id`：平台 user_id，find-or-create 唯一键；唯一索引允许多个
  NULL（PG 语义），存量本地账号为 NULL。
- 数据隔离列由 varchar(36) 拓宽至 varchar(64)，兼容存量 uuid 文本与平台 user_id。

存量数据重映射不在迁移内自动做（无 uuid→user_id 映射来源），由
`provision --auth-user-id` CLI 按账号绑定。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("auth_user_id", sa.String(length=64), nullable=True))
    op.create_index(
        "accounts_auth_user_id_index", "accounts", ["auth_user_id"], unique=True
    )
    op.alter_column(
        "conversations", "from_account_id", type_=sa.String(length=64), existing_type=sa.String(length=36)
    )
    op.alter_column(
        "messages", "created_by", type_=sa.String(length=64), existing_type=sa.String(length=36)
    )
    op.alter_column(
        "upload_files", "created_by", type_=sa.String(length=64), existing_type=sa.String(length=36)
    )
    op.alter_column(
        "dedup_clues", "created_by", type_=sa.String(length=64), existing_type=sa.String(length=36)
    )


def downgrade() -> None:
    op.alter_column(
        "dedup_clues", "created_by", type_=sa.String(length=36), existing_type=sa.String(length=64)
    )
    op.alter_column(
        "upload_files", "created_by", type_=sa.String(length=36), existing_type=sa.String(length=64)
    )
    op.alter_column(
        "messages", "created_by", type_=sa.String(length=36), existing_type=sa.String(length=64)
    )
    op.alter_column(
        "conversations", "from_account_id", type_=sa.String(length=36), existing_type=sa.String(length=64)
    )
    op.drop_index("accounts_auth_user_id_index", table_name="accounts")
    op.drop_column("accounts", "auth_user_id")
