"""本地账号管理 CLI：`python -m app.domain.auth.provision --phone … [--auth-user-id …]`

统一认证接管（2026-09-05）后**无公开注册接口**：普通用户由平台登录、首次访问自动
建档。本 CLI 仅用于管理侧：

- **存量绑定**：`--phone <已有手机号> --auth-user-id <平台 user_id> [--superuser]`
  ——把既有本地账号与平台 user_id 绑定（auth_user_id 唯一键），绑定后平台登录
  命中该本地账号，历史隔离数据（按本地 uuid 聚合）继续按本地 uuid 关联；
  同时可用 --superuser 标注管理员。
- **管理侧建档**：手机号不存在时按参数创建（--password 可选；兼容回退本地登录可用）。

密码经 Argon2id 哈希入库（明文不落盘、不出现在日志）。username 缺省取 phone
（唯一索引约束）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.domain.auth.security import PasswordHasher
from app.infrastructure.database.engine import Database
from app.infrastructure.database.models import Account
from app.interfaces.schemas.auth import AccountStatus


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="本地账号管理（统一认证接管：存量绑定 / 管理员标注；兼容回退登录可用）"
    )
    parser.add_argument("--phone", required=True, help="手机号（存在则绑定，不存在则建档）")
    parser.add_argument("--name", default="", help="显示名（仅建档时用，缺省取 phone）")
    parser.add_argument("--username", default="", help="唯一用户名（缺省取 phone）")
    parser.add_argument(
        "--password",
        default="",
        help="明文密码（可选；兼容回退本地登录可用）",
    )
    parser.add_argument(
        "--auth-user-id",
        default="",
        help="平台 user_id（JWT sub）；绑定后平台登录命中该本地账号（仅登录映射键）",
    )
    parser.add_argument(
        "--superuser",
        action="store_true",
        help="标注超级账号（可访问 GET /users）",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            existing = await session.scalar(
                select(Account).where(Account.phone == args.phone).limit(1)
            )
            if existing is not None:
                return await _bind_existing(session, existing, args)
            return await _create(session, settings, args)
    finally:
        await database.dispose()


async def _bind_existing(session: AsyncSession, row: Account, args: argparse.Namespace) -> int:
    """存量绑定：更新 auth_user_id / is_system（白名单，不覆盖已绑定的 auth_user_id）。"""
    changes: list[str] = []
    if args.auth_user_id:
        if row.auth_user_id and row.auth_user_id != args.auth_user_id:
            print(
                f"账号 {args.phone} 已绑定 auth_user_id={row.auth_user_id}，"
                f"不覆盖为 {args.auth_user_id}",
                file=sys.stderr,
            )
            return 1
        row.auth_user_id = args.auth_user_id
        changes.append("auth_user_id")
    if args.superuser:
        row.is_system = True
        changes.append("superuser")
    if not changes:
        print(
            f"账号 {args.phone} 已存在且无变更项（--auth-user-id / --superuser 至少其一）",
            file=sys.stderr,
        )
        return 1
    await session.commit()
    print(f"已更新账号：{args.phone}（{', '.join(changes)}）")
    return 0


async def _create(session: AsyncSession, settings: Settings, args: argparse.Namespace) -> int:
    """管理侧建档（无注册接口的例外：显式预置系统/管理员账号）。"""
    username = args.username or args.phone
    if await session.scalar(select(Account).where(Account.username == username)) is not None:
        print(f"用户名已存在：{username}", file=sys.stderr)
        return 1
    password_hash = PasswordHasher(settings).hash(args.password) if args.password else None
    session.add(
        Account(
            id=uuid.uuid4(),
            name=args.name or args.phone,
            phone=args.phone,
            username=username,
            password_hash=password_hash,
            is_system=args.superuser,
            auth_user_id=args.auth_user_id or None,
            status=AccountStatus.ACTIVE.value,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        print(f"建档失败（唯一冲突，可能 auth_user_id/username 已占用）：{exc}", file=sys.stderr)
        return 1
    role = "超级用户" if args.superuser else "普通用户"
    binding = f"，auth_user_id={args.auth_user_id}" if args.auth_user_id else ""
    print(f"已创建账号：{args.phone}（{role}，用户名 {username}{binding}）")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
