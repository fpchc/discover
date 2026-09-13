"""会话存储端口（domain/identity）：登录会话的抽象契约。

登录签发令牌对后写入会话存储：访问令牌用于每请求校验，刷新令牌用于轮换续期。
实现必须 **Fail-Closed**——存储不可用时抛 UnauthorizedError，绝不静默放行。

Redis 实现见 `app/infrastructure/redis/session_store.py`；domain 只依赖本协议。
"""

from __future__ import annotations

from typing import Protocol


class KeyValueStore(Protocol):
    """字符串键值存储抽象（infrastructure.redis.Cache 的结构化接口；测试可注入假实现）。"""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def getdel(self, key: str) -> str | None:
        """原子读取并删除 key；key 不存在返回 None（一次性消费，防并发竞态）。"""
        ...


class SessionStore(Protocol):
    """会话存储抽象：登录写入 / 校验存在 / 续期读取 / 登出删除。"""

    async def create_access(self, token: str, account_id: str, *, ttl_seconds: int) -> None:
        """记录访问会话；存储不可用时抛 UnauthorizedError（登录失败）。"""
        ...

    async def exists_access(self, token: str) -> bool:
        """访问会话是否存在；不存在即登录失效。存储异常抛 UnauthorizedError。"""
        ...

    async def create_refresh(self, token: str, account_id: str, *, ttl_seconds: int) -> None:
        """记录刷新会话；存储不可用时抛 UnauthorizedError。"""
        ...

    async def get_refresh(self, token: str) -> str | None:
        """按刷新令牌取 account_id；无此会话返回 None（过期/被轮换/被撤销）。"""
        ...

    async def consume_refresh(self, token: str) -> str | None:
        """原子消费刷新令牌（GETDEL）：返回 account_id 并即时作废，同一令牌只会
        被消费一次（轮换防重用，并发安全）。无此会话返回 None。"""
        ...

    async def revoke_access(self, token: str) -> None:
        """删除访问会话（幂等，key 不存在也成功）。"""
        ...

    async def revoke_refresh(self, token: str) -> None:
        """删除刷新会话（幂等）。"""
        ...


__all__ = ["KeyValueStore", "SessionStore"]
