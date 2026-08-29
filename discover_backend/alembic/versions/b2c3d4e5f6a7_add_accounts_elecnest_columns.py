"""accounts 表新增统一登录列（elecnest_uid / user_type）

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-29

说明：兼容公司统一登录（elecnest SSO）。`user_type` 标记登录来源
（password 手机号+密码 / elecnest 统一登录，默认 password，存量行自动带默认值）；
`elecnest_uid` 存统一登录体系主键 id（对方 uid 的 Long 数字串），唯一索引保证
幂等（find-or-create 按此查重）。既有账号不迁移，保持 user_type=password。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("user_type", sa.String(length=16), nullable=False, server_default="password"),
    )
    op.add_column("accounts", sa.Column("elecnest_uid", sa.String(length=64), nullable=True))
    op.create_index("accounts_elecnest_uid_index", "accounts", ["elecnest_uid"], unique=True)


def downgrade() -> None:
    op.drop_index("accounts_elecnest_uid_index", table_name="accounts")
    op.drop_column("accounts", "elecnest_uid")
    op.drop_column("accounts", "user_type")
