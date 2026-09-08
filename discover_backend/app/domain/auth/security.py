"""密码哈希（Argon2id）与 JWT 令牌校验。

- 密码存 Argon2id PHC 自含编码串（含算法/版本/参数/盐/哈希），无需单独盐列；
  参数经配置注入（time_cost=3 / memory_cost=65536 / parallelism=4）。
- JWT（PyJWT，HS256）：统一认证平台令牌（平台签发，本项目只验签不解发）。
  `decode_platform_token` 按平台契约校验：验签 + exp + aud + iss + type=access。
  `encode` / `decode` 为兼容回退路径（原本地登录签发/校验，sub=本地账号
  uuid；平台令牌仍只验签不解发）。

hash/verify 为 CPU 密集操作，async 路径经 AuthService 用 anyio 线程池包裹，
不在事件循环内阻塞（CLAUDE.md §4）；CLI 预置账号可直调同步方法。
"""

from __future__ import annotations

import time

import argon2
import jwt
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config.settings import Settings
from app.interfaces.schemas.auth import PlatformTokenClaims
from app.shared.errors.base import ConfigError, UnauthorizedError


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
    """HS256 JWT 签发 / 校验（签发仅遗留路径与测试用，验签为平台令牌契约）。"""

    def __init__(self, settings: Settings) -> None:
        if not settings.jwt_secret_key:
            raise ConfigError("缺少 JWT_SECRET_KEY 配置（认证必启用，禁止默认密钥）")
        self._secret = settings.jwt_secret_key
        self._algorithm = settings.jwt_algorithm
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._expires_seconds = settings.auth_access_token_ttl_seconds

    def encode(self, account_id: str) -> str:
        """签发访问令牌（sub = account_id 字符串）。

        含 iss/aud/type=access claims，对齐统一认证平台格式——兼容回退：原本地登录恢复可用，
        encode 签发本地访问令牌（sub=本地账号 uuid），平台生产令牌仍由平台签发。
        """
        now = int(time.time())
        return jwt.encode(
            {
                "sub": account_id,
                "type": "access",
                "iss": self._issuer,
                "aud": self._audience,
                "iat": now,
                "exp": now + self._expires_seconds,
            },
            self._secret,
            algorithm=self._algorithm,
        )

    def decode(self, token: str) -> str:
        """本地令牌校验：验签 + exp + 令牌寿命与 `AUTH_ACCESS_TOKEN_TTL_SECONDS` 同步。

        # pragma: 简化 — PyJWT 对带 aud/iss claim 的令牌默认强制校验（verify_aud/
        verify_iss），本地令牌语义为「仅解签」，显式跳过；受保护请求一律走
        `decode_platform_token`（完整校验 aud/iss/type）。
        令牌寿命同步：`exp - iat > AUTH_ACCESS_TOKEN_TTL_SECONDS` 即视为失效
        （签发与校验共用同一配置，改 TTL 后旧令牌超窗自动作废）。
        """
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"verify_aud": False, "verify_iss": False},
            )
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("登录状态已失效，请重新登录") from exc
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        if (
            isinstance(issued_at, int)
            and isinstance(expires_at, int)
            and expires_at - issued_at > self._expires_seconds
        ):
            raise UnauthorizedError("登录状态已失效，请重新登录")
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise UnauthorizedError("登录状态非法")
        return subject

    def decode_platform_token(self, token: str) -> PlatformTokenClaims:
        """统一认证平台令牌校验（必须全部通过，任一失败 → 401）：

        1. 验签：HS256 + 共享密钥（JWT_SECRET_KEY）
        2. exp 未过期（PyJWT 原生）
        3. aud == jwt_audience（PyJWT audience 参数，防跨受众误用）
        4. iss == jwt_issuer（PyJWT issuer 参数）
        5. type == "access"（手动校验，refresh 令牌不用于业务接口）

        PyJWT 缺 aud/iss claim 或值与参数不符即抛错，一并转 401，不向客户端
        泄露校验细节。

        令牌寿命由平台签发时决定（仅校验 exp 未过期），**不施加本地
        AUTH_ACCESS_TOKEN_TTL_SECONDS**——本地令牌的寿命同步校验见 `decode`
        （deps 兼容解析时经 validate_session 走该路径）。
        """
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
            )
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("登录状态已失效，请重新登录") from exc
        if payload.get("type") != "access":
            raise UnauthorizedError("登录状态非法")
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise UnauthorizedError("登录状态非法")
        return PlatformTokenClaims(
            user_id=subject,
            sid=payload.get("sid"),
            jti=payload.get("jti"),
        )
