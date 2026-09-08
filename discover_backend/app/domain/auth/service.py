"""账号认证服务（AuthService）：统一认证平台验签 / 本地账号解析 / 登录签发 / 账号与用量。

依赖注入：Database、ConversationService、SessionStore 由组装层注入（DIP，CLAUDE.md §6）。

兼容模式（2026-09-07）：统一认证平台令牌为主，原本地登录**恢复可用**作为兼容回退。
- 统一认证：平台令牌本地验签（HS256 + aud + iss + type=access，无 Redis / 无网络），
  平台 user_id（JWT sub）仅按 accounts.auth_user_id **find-or-create** 本地账号（登录映射）；
- 原本地登录（兼容回退）：手机号+密码 / elecnest SSO 签发本地令牌对并写入 Redis
  会话层（SessionStore）；受保护接口对本地令牌（sub=本地账号 uuid）校验 Redis
  访问会话（deps 经 resolve_current_account 区分，登出/过期即 401）。

对外标识与数据隔离键**恒为本地账号 uuid 文本**（str(account.id)），两种登录方式
都不引入第二套用户标识。
"""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import cast

import anyio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config.settings import Settings
from app.domain.auth.security import JwtService, PasswordHasher
from app.domain.auth.session import SessionStore
from app.domain.auth.sso import ElecnestSSOClient
from app.domain.conversation.service import ConversationService
from app.domain.file.service import FileService
from app.infrastructure.database.base import local_now
from app.infrastructure.database.engine import Database
from app.infrastructure.database.models import Account
from app.interfaces.schemas.auth import (
    AccountRecord,
    AccountStatus,
    AvatarConfig,
    DailyUsage,
    ElecnestUserInfo,
    LoginResponse,
    UserType,
    UserUsage,
)
from app.interfaces.schemas.conversations import UsageAggregate
from app.shared.errors.base import BadRequestError, UnauthorizedError

logger = logging.getLogger(__name__)


def _parse_extension_csv(raw: str) -> list[str]:
    """逗号分隔扩展名配置 → 小写去点列表（空段忽略）。"""
    return [part.strip().lower().lstrip(".") for part in raw.split(",") if part.strip()]


def _to_record(row: Account) -> AccountRecord:
    """ORM 账号 → 读取 DTO（password_hash 不外泄）。"""
    return AccountRecord(
        account_id=str(row.id),
        name=row.name,
        phone=row.phone,
        avatar=row.avatar,
        status=AccountStatus(row.status),
        is_system=row.is_system,
        user_type=UserType(row.user_type),
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
        files: FileService,
        elecnest: ElecnestSSOClient | None = None,
        *,
        sessions: SessionStore,
    ) -> None:
        self._settings = settings
        self._db = db
        self._history = history
        self._files = files
        self._elecnest = elecnest
        self._hasher = PasswordHasher(settings)
        self._jwt = JwtService(settings)
        # Redis 会话层为硬依赖（无开关降级），组装层必注入
        self._sessions = sessions

    # ---- 令牌 ----
    def encode_token(self, account_id: str) -> str:
        """签发 JWT 访问令牌（兼容回退：原本地登录签发，sub=本地账号 uuid）。"""
        return self._jwt.encode(account_id)

    def decode_token(self, token: str) -> str:
        """兼容回退校验 JWT 返回 account_id（不校验 aud/iss/type；仅本地会话用）。"""
        return self._jwt.decode(token)

    def validate_platform_token(self, token: str) -> str:
        """统一认证平台令牌校验（本地验签，无 Redis / 无网络）：返回平台 user_id。

        校验矩阵（验签 + exp + aud + iss + type=access）见 JwtService；
        任一失败抛 UnauthorizedError（HTTP 401）。
        """
        return self._jwt.decode_platform_token(token).user_id

    # ---- 用户解析（find-or-create，统一认证自动建档） ----
    async def resolve_user(self, user_id: str) -> AccountRecord | None:
        """按平台 user_id 解析本地账号：无则自动建档（user_type=unified），有则复用。

        统一登录映射：平台 user_id（JWT sub）经 auth_user_id 找到/建档本地账号，
        返回的 account_id 恒为本地 uuid 文本。建档幂等：并发首访撞唯一索引时
        回滚后二次查询兜底（一个平台用户对应一个本地账号）。默认名「用户{user_id}」，
        昵称可后续 PATCH /users/me 修改。建档失败返回 None（调用方转 401）。
        """
        async with self._db.session_factory() as session:
            row = await session.scalar(
                select(Account).where(Account.auth_user_id == user_id).limit(1)
            )
            if row is None:
                # pragma: 简化 — username 唯一索引仅信息用途（无业务读取），按
                # user_id 派生唯一名，超长截断兜底列宽 64（截断冲突概率极低）
                row = Account(
                    id=uuid.uuid4(),
                    name=f"用户{user_id}",
                    phone="",
                    username=f"unified_{user_id}"[:64],
                    auth_user_id=user_id,
                    user_type=UserType.UNIFIED.value,
                    status=AccountStatus.ACTIVE.value,
                )
                session.add(row)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    row = await session.scalar(
                        select(Account).where(Account.auth_user_id == user_id).limit(1)
                    )
                    if row is None:
                        return None
            return _to_record(row)

    async def resolve_current_account(self, token: str) -> AccountRecord | None:
        """兼容解析当前账号：平台令牌 find-or-create / 原本地登录令牌直查。

        1. 本地验签（HS256 + aud + iss + type=access）解出 sub；
        2. sub 若为本地账号 uuid（原本地登录令牌，sub=accounts.id）→ 按 id 直查
           并校验 Redis 访问会话存在（登出/过期即 401，原登录语义）；
        3. 否则视为平台 user_id（统一认证令牌）→ resolve_user find-or-create
           （按 auth_user_id 登录映射，建档失败返回 None）。
        """
        user_id = self.validate_platform_token(token)
        local = await self.get_account(user_id)
        if local is not None:
            await self.validate_session(token)
            return local
        return await self.resolve_user(user_id)

    # ---- 会话（Redis 权威：key 缺失即登录失效） ----
    async def validate_session(self, token: str) -> str:
        """校验 JWT 且访问会话存在：无效/过期/Redis 无此会话 → 401。

        Redis 是访问会话的唯一事实来源——key 缺失即登录失效，即使 JWT 未过期。
        """
        account_id = self.decode_token(token)
        if not await self._sessions.exists_access(token):
            raise UnauthorizedError("登录状态已失效，请重新登录")
        return account_id

    async def refresh(self, refresh_token: str) -> LoginResponse:
        """刷新令牌换新令牌对（轮换制）：旧刷新令牌原子消费作废，防重用。

        consume_refresh 用 Redis GETDEL 读+删一步完成——同一刷新令牌并发下也只会
        被消费一次，不存在「检查后再删」的竞态。
        """
        account_id = await self._sessions.consume_refresh(refresh_token)
        if account_id is None:
            raise UnauthorizedError("登录状态已失效，请重新登录")
        return await self._establish_session(account_id, None)

    async def logout(self, access_token: str, refresh_token: str) -> None:
        """服务端登出：作废访问会话 + 刷新会话（DEL 幂等，key 不存在也成功）。"""
        await self._sessions.revoke_access(access_token)
        await self._sessions.revoke_refresh(refresh_token)

    async def _establish_session(self, account_id: str, name: str | None) -> LoginResponse:
        """签发令牌对 + 写入 Redis 会话层，组装登录/刷新响应。"""
        access, refresh = await self._issue_and_store_pair(account_id)
        return LoginResponse(
            account_id=account_id,
            token=access,
            refresh_token=refresh,
            expires_in=self._settings.auth_access_token_ttl_seconds,
            name=name,
        )

    async def _issue_and_store_pair(self, account_id: str) -> tuple[str, str]:
        """签发访问令牌（JWT）+ 刷新令牌（不透明随机串）并写入 Redis 会话层。"""
        access = self._jwt.encode(account_id)
        refresh = secrets.token_urlsafe(32)
        await self._sessions.create_access(
            access, account_id, ttl_seconds=self._settings.auth_access_token_ttl_seconds
        )
        await self._sessions.create_refresh(
            refresh, account_id, ttl_seconds=self._settings.auth_refresh_token_ttl_seconds
        )
        return access, refresh

    # ---- 登录 ----
    async def login(self, phone: str, password: str) -> LoginResponse:
        """手机号 + 密码登录：统一错误文案防账号枚举；成功签发访问+刷新令牌。"""
        account = await self._find_by_phone(phone)
        if account is None or account.password_hash is None:
            raise UnauthorizedError("手机号或密码错误")
        if account.status != AccountStatus.ACTIVE.value:
            raise UnauthorizedError("账号不可用")
        ok = await anyio.to_thread.run_sync(self._hasher.verify, account.password_hash, password)
        if not ok:
            raise UnauthorizedError("手机号或密码错误")
        response = await self._establish_session(str(account.id), account.name)
        await self._record_login(account.id)
        return response

    async def login_with_elecnest(self, token: str, uid: int) -> LoginResponse:
        """公司统一登录：token + uid → 用户信息 → 本地注册/复用 → 签发访问+刷新令牌。"""
        if not self._settings.elecnest_sso_enabled:
            raise BadRequestError("统一登录未启用")
        assert self._elecnest is not None
        info = await self._elecnest.get_user_info(token=token, uid=uid)
        if info is None:
            raise UnauthorizedError("统一登录校验失败")
        uid_text = str(uid)
        account_id = await self._upsert_elecnest_account(uid_text, info)
        name = info.nickname or info.username
        return await self._establish_session(account_id, name)

    async def _upsert_elecnest_account(self, uid_text: str, info: ElecnestUserInfo) -> str:
        """按 elecnest_uid 查账号：无则创建（user_type=elecnest），有则更新显示名/头像。"""
        name = info.nickname or info.username or f"用户{uid_text}"
        async with self._db.session_factory() as session:
            row = await session.scalar(
                select(Account).where(Account.elecnest_uid == uid_text).limit(1)
            )
            if row is None:
                row = Account(
                    id=uuid.uuid4(),
                    name=name,
                    phone=info.phone or "",
                    username=info.username or f"elecnest_{uid_text}",
                    avatar=info.avatar,
                    user_type=UserType.ELECNEST.value,
                    elecnest_uid=uid_text,
                    status=AccountStatus.ACTIVE.value,
                )
                session.add(row)
            else:
                if row.status != AccountStatus.ACTIVE.value:
                    raise UnauthorizedError("账号不可用")
                # 存在则更新统一登录最新信息（本平台账号字段：显示名/手机号/头像）
                row.name = name
                row.user_type = UserType.ELECNEST.value
                if info.phone:
                    row.phone = info.phone
                if info.avatar:
                    row.avatar = info.avatar
            row.last_login_at = local_now()
            row.last_active_at = local_now()
            await session.commit()
            return str(row.id)

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

    # ---- 资料维护（头像 / 昵称 / 密码） ----
    async def avatar_config(self) -> AvatarConfig:
        """当前头像上传限制（前端本地校验用；阈值全部配置驱动）。"""
        return AvatarConfig(
            max_size_bytes=self._settings.avatar_max_size_bytes,
            allowed_extensions=_parse_extension_csv(self._settings.avatar_allowed_extensions),
            max_dimension=self._settings.avatar_max_dimension,
            min_dimension=self._settings.avatar_min_dimension,
        )

    async def update_account(self, account_id: str, *, name: str | None) -> AccountRecord:
        """更新当前账号昵称；name 为空则保持原值（白名单字段，防越权改 phone 等）。

        按本地账号 uuid 定位（对外标识唯一口径）。
        """
        if name is not None and not name.strip():
            raise BadRequestError("昵称不能为空")
        try:
            uid = uuid.UUID(account_id)
        except ValueError:
            raise UnauthorizedError("账号不存在") from None
        async with self._db.session_factory() as session:
            row = await session.get(Account, uid)
            if row is None:
                raise UnauthorizedError("账号不存在")
            if name is not None:
                row.name = name.strip()
            row.updated_at = local_now()
            await session.commit()
            return _to_record(row)

    async def change_avatar(
        self,
        account_id: str,
        *,
        filename: str,
        content: bytes,
        mimetype: str,
    ) -> AccountRecord:
        """更换头像：FileService 校验落盘，回写 Account.avatar 为预览相对路径。

        created_by 与账号定位统一用本地账号 uuid。
        """
        file = await self._files.upload_avatar(
            created_by=account_id,
            filename=filename,
            content=content,
            mimetype=mimetype,
        )
        avatar_path = f"/files/{file.file_id}/preview"
        try:
            uid = uuid.UUID(account_id)
        except ValueError:
            raise UnauthorizedError("账号不存在") from None
        async with self._db.session_factory() as session:
            row = await session.get(Account, uid)
            if row is None:
                raise UnauthorizedError("账号不存在")
            row.avatar = avatar_path
            row.updated_at = local_now()
            await session.commit()
            return _to_record(row)

    async def change_password(
        self,
        account_id: str,
        *,
        old_password: str,
        new_password: str,
    ) -> AccountRecord:
        """修改密码：校验原密码 + 新密码长度；成功回写 Argon2id 哈希。"""
        min_length = self._settings.account_password_min_length
        if len(new_password) < min_length:
            raise BadRequestError(f"新密码至少 {min_length} 位")
        try:
            uid = uuid.UUID(account_id)
        except ValueError:
            raise UnauthorizedError("账号不存在") from None
        async with self._db.session_factory() as session:
            row = await session.get(Account, uid)
            if row is None:
                raise UnauthorizedError("账号不存在")
            if row.password_hash is None:
                raise BadRequestError("当前账号未设置密码，无法修改")
            ok = await anyio.to_thread.run_sync(
                self._hasher.verify, row.password_hash, old_password
            )
            if not ok:
                raise UnauthorizedError("原密码错误")
            row.password_hash = await anyio.to_thread.run_sync(self._hasher.hash, new_password)
            row.updated_at = local_now()
            await session.commit()
            return _to_record(row)

    # ---- 账号与用量 ----
    async def get_account(self, account_id: str) -> AccountRecord | None:
        """按本地账号 uuid 查账号（纯查询，不建档）；无则返回 None。"""
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
        """当前账号 token 用量（按 created_by = 本地账号 uuid 聚合 messages）。"""
        account = await self.get_account(account_id)
        if account is None:
            return None
        usage = await self._history.aggregate_user_usage(account_id)
        return UserUsage(account_id=account_id, name=account.name, **usage.model_dump())

    async def get_user_daily_usage(self, account_id: str, *, days: int) -> DailyUsage | None:
        """当前账号近 days 天每日用量（趋势图数据源；口径同 get_user_usage）。"""
        account = await self.get_account(account_id)
        if account is None:
            return None
        items = await self._history.aggregate_daily_usage(account_id, days=days)
        return DailyUsage(account_id=account_id, name=account.name, days=days, items=items)

    async def list_users_with_usage(self) -> list[UserUsage]:
        """全部账号用量（超级用户接口）：accounts x messages.created_by 聚合。

        账号标识恒为本地 uuid 文本，与 messages.created_by 存值一致（无第二标识）。
        """
        async with self._db.session_factory() as session:
            rows = (await session.scalars(select(Account).order_by(Account.created_at))).all()
        aggregates = await self._history.usage_by_account()
        result: list[UserUsage] = []
        for row in rows:
            account_id = str(row.id)
            usage = aggregates.get(account_id) or UsageAggregate()
            result.append(UserUsage(account_id=account_id, name=row.name, **usage.model_dump()))
        return result
