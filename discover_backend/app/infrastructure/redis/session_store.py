"""登录会话存储的 Redis 实现（fail-closed 异常边界）。

键命名空间：访问令牌 `auth:access:{sha256(token)}`、刷新令牌
`auth:refresh:{sha256(token)}`，TTL 以配置为准。

**Fail-Closed**：任何 RedisError 一律转 UnauthorizedError（401），不向客户端暴露
内部架构细节——校验失败视为登录失效，写入失败视为登录/刷新失败。
"""

from __future__ import annotations

import hashlib
import logging

import redis.exceptions

from app.domain.identity.ports import KeyValueStore
from app.shared.errors.base import UnauthorizedError

logger = logging.getLogger(__name__)

# Redis 键命名空间前缀（统一隔离，避免与平台其他 Redis 键冲突）。
_ACCESS_PREFIX: str = "auth:access:"
_REFRESH_PREFIX: str = "auth:refresh:"


def access_key(token: str) -> str:
    """访问会话 key：前缀 + token 的 SHA-256（固定 64 位 hex，避免超长 JWT 直接作 key）。"""
    return f"{_ACCESS_PREFIX}{_digest(token)}"


def refresh_key(token: str) -> str:
    """刷新会话 key：前缀 + 刷新令牌的 SHA-256。"""
    return f"{_REFRESH_PREFIX}{_digest(token)}"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RedisSessionStore:
    """基于 Redis 的会话存储：KeyValueStore 封装 + fail-closed 异常边界。"""

    def __init__(self, kv: KeyValueStore) -> None:
        self._kv = kv

    async def create_access(self, token: str, account_id: str, *, ttl_seconds: int) -> None:
        await self._set(access_key(token), account_id, ttl_seconds, fail_message="访问会话写入")

    async def exists_access(self, token: str) -> bool:
        return await self._get(access_key(token), fail_message="访问会话校验") is not None

    async def create_refresh(self, token: str, account_id: str, *, ttl_seconds: int) -> None:
        await self._set(refresh_key(token), account_id, ttl_seconds, fail_message="刷新会话写入")

    async def get_refresh(self, token: str) -> str | None:
        return await self._get(refresh_key(token), fail_message="刷新会话校验")

    async def consume_refresh(self, token: str) -> str | None:
        try:
            return await self._kv.getdel(refresh_key(token))
        except redis.exceptions.RedisError as exc:
            logger.error("刷新会话消费失败（Redis 不可用）：%s", exc)
            raise UnauthorizedError("登录状态已失效，请重新登录") from exc

    async def revoke_access(self, token: str) -> None:
        await self._delete(access_key(token), fail_message="访问会话删除")

    async def revoke_refresh(self, token: str) -> None:
        await self._delete(refresh_key(token), fail_message="刷新会话删除")

    # ---- 私有：统一异常边界 ----

    async def _get(self, key: str, *, fail_message: str) -> str | None:
        try:
            return await self._kv.get(key)
        except redis.exceptions.RedisError as exc:
            logger.error("%s失败（Redis 不可用）：%s", fail_message, exc)
            raise UnauthorizedError("登录状态已失效，请重新登录") from exc

    async def _set(self, key: str, value: str, ttl_seconds: int, *, fail_message: str) -> None:
        try:
            await self._kv.set(key, value, ttl_seconds=ttl_seconds)
        except redis.exceptions.RedisError as exc:
            logger.error("%s失败（Redis 不可用）：%s", fail_message, exc)
            raise UnauthorizedError("登录失败，请稍后重试") from exc

    async def _delete(self, key: str, *, fail_message: str) -> None:
        try:
            await self._kv.delete(key)
        except redis.exceptions.RedisError as exc:
            logger.error("%s失败（Redis 不可用）：%s", fail_message, exc)
            raise UnauthorizedError("登出失败，请稍后重试") from exc


__all__ = ["RedisSessionStore", "access_key", "refresh_key"]
