"""账号认证服务（AuthService）：登录 / 账号查询 / 用量聚合。

依赖注入：Database 与 ConversationService 由组装层注入（DIP，CLAUDE.md §6）。
密码哈希为 CPU 密集，登录校验经 anyio 线程池；DB 非关键路径（登录时间记录）
best-effort 忽略（与 record_turn 舱壁哲学一致）。认证本身是硬依赖，不降级。
"""

from __future__ import annotations

import logging
import uuid
from typing import cast

import anyio
from sqlalchemy import select

from app.config.settings import Settings
from app.db.base import local_now
from app.db.engine import Database
from app.db.models import Account
from app.errors.base import UnauthorizedError
from app.schemas.auth import (
    AccountRecord,
    AccountStatus,
    LoginResponse,
    UserUsage,
)
from app.schemas.conversations import UsageAggregate
from app.services.auth_security import JwtService, PasswordHasher
from app.services.conversations import ConversationService

logger = logging.getLogger(__name__)


def _to_record(row: Account) -> AccountRecord:
    """ORM 账号 → 读取 DTO（password_hash 不外泄）。"""
    return AccountRecord(
        account_id=str(row.id),
        name=row.name,
        phone=row.phone,
        avatar=row.avatar,
        status=AccountStatus(row.status),
        is_system=row.is_system,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


class AuthService:
    """账号认证门面：登录签发 / 令牌校验 / 账号与用量查询。"""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        history: ConversationService,
    ) -> None:
        self._settings = settings
        self._db = db
        self._history = history
        self._hasher = PasswordHasher(settings)
        self._jwt = JwtService(settings)

    # ---- 令牌 ----
    def encode_token(self, account_id: str) -> str:
        """签发 JWT（登录用；测试经此构造令牌）。"""
        return self._jwt.encode(account_id)

    def decode_token(self, token: str) -> str:
        """校验 JWT 返回 account_id；无效/过期抛 UnauthorizedError。"""
        return self._jwt.decode(token)

    # ---- 登录 ----
    async def login(self, phone: str, password: str) -> LoginResponse:
        """手机号 + 密码登录：统一错误文案防账号枚举；成功签发 JWT。"""
        account = await self._find_by_phone(phone)
        if account is None or account.password_hash is None:
            raise UnauthorizedError("手机号或密码错误")
        if account.status != AccountStatus.ACTIVE.value:
            raise UnauthorizedError("账号不可用")
        ok = await anyio.to_thread.run_sync(self._hasher.verify, account.password_hash, password)
        if not ok:
            raise UnauthorizedError("手机号或密码错误")
        token = self._jwt.encode(str(account.id))
        await self._record_login(account.id)
        return LoginResponse(account_id=str(account.id), token=token, name=account.name)

    async def _find_by_phone(self, phone: str) -> Account | None:
        async with self._db.session_factory() as session:
            return cast(
                Account | None,
                await session.scalar(select(Account).where(Account.phone == phone).limit(1)),
            )

    async def _record_login(self, account_id: uuid.UUID) -> None:
        """回写 last_login_at / last_active_at（best-effort）。"""
        try:
            async with self._db.session_factory() as session:
                row = await session.get(Account, account_id)
                if row is None:
                    return
                row.last_login_at = local_now()
                row.last_active_at = local_now()
                await session.commit()
        except Exception:
            logger.warning("登录时间记录失败（best-effort 忽略）：%s", account_id)

    # ---- 账号与用量 ----
    async def get_account(self, account_id: str) -> AccountRecord | None:
        """按 account_id 查账号（uuid 文本；非法/不存在返回 None）。"""
        try:
            uid = uuid.UUID(account_id)
        except ValueError:
            return None
        async with self._db.session_factory() as session:
            row = await session.get(Account, uid)
        if row is None:
            return None
        return _to_record(row)

    async def get_user_usage(self, account_id: str) -> UserUsage | None:
        """当前账号 token 用量（按 created_by 聚合 messages）。"""
        account = await self.get_account(account_id)
        if account is None:
            return None
        usage = await self._history.aggregate_user_usage(account_id)
        return UserUsage(account_id=account_id, name=account.name, **usage.model_dump())

    async def list_users_with_usage(self) -> list[UserUsage]:
        """全部账号用量（超级用户接口）：accounts x messages.created_by 聚合。"""
        async with self._db.session_factory() as session:
            rows = (await session.scalars(select(Account).order_by(Account.created_at))).all()
        aggregates = await self._history.usage_by_account()
        result: list[UserUsage] = []
        for row in rows:
            account_id = str(row.id)
            usage = aggregates.get(account_id) or UsageAggregate()
            result.append(UserUsage(account_id=account_id, name=row.name, **usage.model_dump()))
        return result
