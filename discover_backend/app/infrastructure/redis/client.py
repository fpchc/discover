"""Redis 扩展：客户端连接池 + 轻量 Cache / Lock 封装（恒启用）。

Redis 为认证会话层的硬依赖（登录会话 / 令牌过期 / 撤销 / 续期以 Redis 为准），
无启用开关。startup 惰性不 ping：Redis 宕机不阻塞应用启动，首次使用时才报错
（与 Database 惰性建连一致）。Cache 值按字符串处理，JSON 序列化由调用方负责。
"""

from __future__ import annotations

from typing import Final
from uuid import uuid4

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.config.settings import active_settings

# 释放锁的 Lua 脚本：仅当持有者 token 匹配时删除（防误删他人持有的锁）。
_UNLOCK_SCRIPT: Final[str] = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class Cache:
    """字符串值缓存封装：get / set / delete（TTL 秒）。"""

    def __init__(self, client: aioredis.Redis, default_ttl_seconds: int) -> None:
        self._client = client
        self._default_ttl_seconds = default_ttl_seconds

    async def get(self, key: str) -> str | None:
        value = await self._client.get(key)
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        await self._client.set(key, value, ex=ttl_seconds or self._default_ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def getdel(self, key: str) -> str | None:
        """原子读取并删除 key（GETDEL）：key 不存在返回 None。

        用于一次性消费（如刷新令牌轮换）——读+删单命令完成，消除「检查后再删」
        的并发竞态（同一 key 只会被消费一次）。
        """
        value = await self._client.getdel(key)
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class Lock:
    """基于 SET NX PX 的分布式锁：acquire / release（持有者 token 校验）。"""

    def __init__(self, client: aioredis.Redis, default_timeout_seconds: float) -> None:
        self._client = client
        self._default_timeout_seconds = default_timeout_seconds
        self._unlock = client.register_script(_UNLOCK_SCRIPT)

    async def acquire(self, name: str, *, timeout_seconds: float | None = None) -> str | None:
        """尝试获取锁；成功返回持有者 token（释放时校验），失败返回 None。"""
        timeout = timeout_seconds or self._default_timeout_seconds
        token = uuid4().hex
        acquired = await self._client.set(name, token, nx=True, px=int(timeout * 1000))
        return token if acquired else None

    async def release(self, name: str, token: str) -> None:
        await self._unlock(keys=[name], args=[token])


_client: aioredis.Redis | None = None
_cache: Cache | None = None
_lock: Lock | None = None


def is_enabled() -> bool:
    """Redis 为认证会话层的硬依赖：恒启用（无开关）。"""
    return True


def init_app(app: FastAPI | None) -> None:
    """构造 Redis 客户端与轻量封装。"""
    global _client, _cache, _lock
    settings = active_settings()
    _client = aioredis.from_url(settings.redis_url)
    _cache = Cache(_client, settings.redis_cache_default_ttl_seconds)
    _lock = Lock(_client, settings.redis_lock_default_timeout_seconds)


async def startup(app: FastAPI) -> None:
    """惰性连接：无操作。"""


async def shutdown(app: FastAPI) -> None:
    """关闭连接池。"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_client() -> aioredis.Redis:
    """取 Redis 客户端；扩展未启用时抛断言。"""
    assert _client is not None
    return _client


def get_cache() -> Cache:
    """取缓存封装。"""
    assert _cache is not None
    return _cache


def get_lock() -> Lock:
    """取分布式锁封装。"""
    assert _lock is not None
    return _lock
