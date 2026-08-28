"""密码哈希（Argon2id）与 JWT 会话令牌。

- 密码存 Argon2id PHC 自含编码串（含算法/版本/参数/盐/哈希），无需单独盐列；
  参数经配置注入（time_cost=3 / memory_cost=65536 / parallelism=4）。
- JWT（PyJWT，HS256）：sub 承载 account_id 字符串；签名密钥必须由环境注入。

hash/verify 为 CPU 密集操作，async 路径经 AuthService 用 anyio 线程池包裹，
不在事件循环内阻塞（CLAUDE.md §4）；CLI 预置账号可直调同步方法。
"""

from __future__ import annotations

import time

import argon2
import jwt
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config.settings import Settings
from app.errors.base import ConfigError, UnauthorizedError


class PasswordHasher:
    """Argon2id 密码哈希。"""

    def __init__(self, settings: Settings) -> None:
        self._hasher = argon2.PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost,
            parallelism=settings.argon2_parallelism,
        )

    def hash(self, password: str) -> str:
        """生成 Argon2id PHC 编码串。"""
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """校验密码；密码不符或存量哈希畸形一律返回 False（不抛异常）。"""
        try:
            self._hasher.verify(password_hash, password)
            return True
        # InvalidHashError 继承 ValueError（非 VerificationError），需一并拦截
        except (VerifyMismatchError, InvalidHashError, VerificationError):
            return False


class JwtService:
    """HS256 JWT 签发 / 校验。"""

    def __init__(self, settings: Settings) -> None:
        if not settings.jwt_secret_key:
            raise ConfigError("缺少 JWT_SECRET_KEY 配置（认证必启用，禁止默认密钥）")
        self._secret = settings.jwt_secret_key
        self._algorithm = settings.jwt_algorithm
        self._expires_seconds = settings.jwt_expires_minutes * 60

    def encode(self, account_id: str) -> str:
        """签发访问令牌（sub = account_id 字符串）。"""
        now = int(time.time())
        return jwt.encode(
            {"sub": account_id, "iat": now, "exp": now + self._expires_seconds},
            self._secret,
            algorithm=self._algorithm,
        )

    def decode(self, token: str) -> str:
        """校验并返回 account_id；无效/过期抛 UnauthorizedError（HTTP 401）。"""
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("登录状态已失效，请重新登录") from exc
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise UnauthorizedError("登录状态非法")
        return subject
