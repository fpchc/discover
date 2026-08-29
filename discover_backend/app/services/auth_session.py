"""登录会话存储层：以 Redis 为权威的令牌会话（访问令牌 + 刷新令牌）。

登录签发令牌对后写入 Redis：访问令牌 `auth:access:{sha256(token)}`、刷新令牌
`auth:refresh:{sha256(token)}`，TTL 各自以配置为准。每次受保护请求校验访问会话
存在——Redis 中没有即登录失效（401）；刷新令牌存在性决定能否续期。

**Fail-Closed**：任何 RedisError 一律转 UnauthorizedError（401），不向客户端暴露
内部架构细节——校验失败视为登录失效，写入失败视为登录/刷新失败。

Redis 为认证会话层的硬依赖（无启用开关）：容器恒注入 RedisSessionStore。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

import redis.exceptions

from app.errors.base import UnauthorizedError

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


class KeyValueStore(Protocol):
    """字符串键值存储抽象（ext_redis.Cache 的结构化接口；测试可注入内存假实现）。"""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def getdel(self, key: str) -> str | None:
        """原子读取并删除 key；key 不存在返回 None（一次性消费，防并发竞态）。"""
        ...


class SessionStore(Protocol):
    """会话存储抽象：登录写入 / 校验存在 / 续期读取 / 登出删除。"""

    async def create_access(self, token: str, account_id: str, *, ttl_seconds: int) -> None:
        """记录访问会话；Redis 不可用时抛 UnauthorizedError（登录失败）。"""
        ...

    async def exists_access(self, token: str) -> bool:
        """访问会话是否存在；不存在即登录失效。Redis 异常抛 UnauthorizedError。"""
        ...

    async def create_refresh(self, token: str, account_id: str, *, ttl_seconds: int) -> None:
        """记录刷新会话；Redis 不可用时抛 UnauthorizedError。"""
        ...

    async def get_refresh(self, token: str) -> str | None:
        """按刷新令牌取 account_id；无此会话返回 None（过期/被轮换/被撤销）。"""
        ...

    async def consume_refresh(self, token: str) -> str | None:
        """原子消费刷新令牌（GETDEL）：返回 account_id 并即时作废，同一令牌只会
        被消费一次（轮换防重用，并发安全）。无此会话返回 None。"""
        ...

    async def revoke_access(self, token: str) -> None:
        """删除访问会话（DEL 幂等，key 不存在也成功）。"""
        ...

    async def revoke_refresh(self, token: str) -> None:
        """删除刷新会话（DEL 幂等）。"""
        ...


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
