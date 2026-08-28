"""预置账号 CLI：`python -m app.auth.provision --phone … --name … --password …`

无公开注册接口（用户决策）；用户由管理侧经此脚本预置，密码经 Argon2id 哈希
入库（明文不落盘、不出现在日志）。username 缺省取 phone（唯一索引约束）；
--superuser 标注超级账号（is_system=true，可访问全量用量接口）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select

from app.auth.models import AccountStatus
from app.auth.security import PasswordHasher
from app.config.settings import Settings
from app.db.engine import Database
from app.db.models import Account


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="预置平台账号（手机号 + 密码）")
    parser.add_argument("--phone", required=True, help="登录手机号")
    parser.add_argument("--name", required=True, help="显示名")
    parser.add_argument("--username", default="", help="唯一用户名（缺省取 phone）")
    parser.add_argument("--password", required=True, help="明文密码（仅本次进程使用）")
    parser.add_argument("--superuser", action="store_true", help="标注超级账号")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    password_hash = PasswordHasher(settings).hash(args.password)
    username = args.username or args.phone
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            if await session.scalar(select(Account).where(Account.phone == args.phone)) is not None:
                print(f"手机号已存在：{args.phone}", file=sys.stderr)
                return 1
            has_username = await session.scalar(select(Account).where(Account.username == username))
            if has_username is not None:
                print(f"用户名已存在：{username}", file=sys.stderr)
                return 1
            session.add(
                Account(
                    id=uuid.uuid4(),
                    name=args.name,
                    phone=args.phone,
                    username=username,
                    password_hash=password_hash,
                    is_system=args.superuser,
                    status=AccountStatus.ACTIVE.value,
                )
            )
            await session.commit()
    finally:
        await database.dispose()
    role = "超级用户" if args.superuser else "普通用户"
    print(f"已创建账号：{args.phone}（{role}，用户名 {username}）")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
