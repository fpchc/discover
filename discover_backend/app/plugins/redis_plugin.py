"""redis 插件：客户端连接池 + 轻量 Cache / Lock 封装（默认 redis_enabled=false）。

startup 惰性不 ping：Redis 宕机不阻塞应用启动，首次使用时才报错（与 Database
惰性建连一致）。Cache 值按字符串处理，JSON 序列化由调用方负责。
"""

from __future__ import annotations

from typing import Final
from uuid import uuid4

import redis.asyncio as aioredis

from app.config.settings import Settings
from app.plugins.base import Plugin, register

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


@register
class RedisPlugin(Plugin):
    """Redis 客户端 + Cache / Lock 封装。"""

    name = "redis"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = aioredis.from_url(settings.redis_url)
        self._cache = Cache(self._client, settings.redis_cache_default_ttl_seconds)
        self._lock = Lock(self._client, settings.redis_lock_default_timeout_seconds)

    @classmethod
    def is_enabled(cls, settings: Settings) -> bool:
        return settings.redis_enabled

    @property
    def client(self) -> aioredis.Redis:
        return self._client

    @property
    def cache(self) -> Cache:
        return self._cache

    @property
    def lock(self) -> Lock:
        return self._lock

    async def startup(self) -> None:
        """惰性连接：无操作。"""

    async def shutdown(self) -> None:
        await self._client.aclose()
