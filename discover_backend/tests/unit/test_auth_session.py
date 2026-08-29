"""会话存储层单测：key 规范 / RedisSessionStore 写·校验·删 / fail-closed / Null 降级。

无网络 / 无 DB / 无真实 Redis：用内存假 KeyValueStore（Duck typing 满足协议）
验证访问/刷新会话语义与 RedisError 异常边界（CLAUDE.md §12：外部 I/O 一律注入
mock，禁真实连接）。
"""

from __future__ import annotations

import pytest
from app.errors.base import UnauthorizedError
from app.services.auth_session import (
    KeyValueStore,
    RedisSessionStore,
    access_key,
    refresh_key,
)
from redis.exceptions import RedisError


class _FakeKV(KeyValueStore):
    """内存键值存储：模拟 Redis 语义，可按操作注入失败（fail-closed 用例）。"""

    def __init__(self, *, fail_ops: set[str] | None = None) -> None:
        self._data: dict[str, str] = {}
        self._fail_ops = fail_ops or set()

    async def get(self, key: str) -> str | None:
        self._raise_if_fail("get")
        return self._data.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        del ttl_seconds
        self._raise_if_fail("set")
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._raise_if_fail("delete")
        self._data.pop(key, None)

    async def getdel(self, key: str) -> str | None:
        self._raise_if_fail("getdel")
        return self._data.pop(key, None)

    def _raise_if_fail(self, op: str) -> None:
        if op in self._fail_ops:
            raise RedisError("模拟 Redis 不可用")


# ---- key 规范：前缀 + sha256，避免超长 JWT 直接作 key ----


def test_access_key_hashed_and_prefixed() -> None:
    key = access_key("token-1")
    assert key.startswith("auth:access:")
    assert len(key) == len("auth:access:") + 64  # sha256 hex
    assert access_key("token-1") == key  # 确定性
    assert access_key("token-1") != access_key("token-2")


def test_refresh_key_prefixed_and_distinct_namespace() -> None:
    key = refresh_key("token-1")
    assert key.startswith("auth:refresh:")
    assert key != access_key("token-1")  # 两通道命名空间隔离


# ---- RedisSessionStore：正常写 / 校验 / 删 ----


async def test_access_create_exists_revoke_roundtrip() -> None:
    store = RedisSessionStore(_FakeKV())
    await store.create_access("access-1", "acc-1", ttl_seconds=3600)
    assert await store.exists_access("access-1") is True
    await store.revoke_access("access-1")
    assert await store.exists_access("access-1") is False
    await store.revoke_access("access-1")  # DEL 幂等：key 不存在也成功


async def test_refresh_create_get_revoke_roundtrip() -> None:
    store = RedisSessionStore(_FakeKV())
    await store.create_refresh("refresh-1", "acc-1", ttl_seconds=604800)
    assert await store.get_refresh("refresh-1") == "acc-1"
    await store.revoke_refresh("refresh-1")
    assert await store.get_refresh("refresh-1") is None


async def test_consume_refresh_atomic_once() -> None:
    """GETDEL 原子消费：第一次取到并作废，第二次即 None（轮换防重用）。"""
    store = RedisSessionStore(_FakeKV())
    await store.create_refresh("r1", "acc-1", ttl_seconds=604800)
    assert await store.consume_refresh("r1") == "acc-1"
    assert await store.consume_refresh("r1") is None  # 已被消费
    assert await store.get_refresh("r1") is None


async def test_exists_missing_token_false() -> None:
    store = RedisSessionStore(_FakeKV())
    assert await store.exists_access("never-created") is False
    assert await store.get_refresh("never-created") is None


async def test_access_and_refresh_namespaces_isolated() -> None:
    """同串写入访问/刷新通道互不串扰（key 前缀隔离）。"""
    store = RedisSessionStore(_FakeKV())
    await store.create_access("same", "acc-a", ttl_seconds=3600)
    await store.create_refresh("same", "acc-b", ttl_seconds=604800)
    assert await store.get_refresh("same") == "acc-b"
    await store.revoke_refresh("same")
    assert await store.exists_access("same") is True  # 访问通道不受影响


# ---- RedisSessionStore：fail-closed（Redis 异常一律 401，不泄露细节） ----


async def test_exists_redis_error_raises_unauthorized() -> None:
    store = RedisSessionStore(_FakeKV(fail_ops={"get"}))
    with pytest.raises(UnauthorizedError):
        await store.exists_access("t")


async def test_get_refresh_redis_error_raises_unauthorized() -> None:
    store = RedisSessionStore(_FakeKV(fail_ops={"get"}))
    with pytest.raises(UnauthorizedError):
        await store.get_refresh("t")


async def test_create_redis_error_raises_unauthorized() -> None:
    store = RedisSessionStore(_FakeKV(fail_ops={"set"}))
    with pytest.raises(UnauthorizedError):
        await store.create_access("t", "acc", ttl_seconds=3600)


async def test_revoke_redis_error_raises_unauthorized() -> None:
    store = RedisSessionStore(_FakeKV(fail_ops={"delete"}))
    with pytest.raises(UnauthorizedError):
        await store.revoke_refresh("t")


async def test_consume_refresh_redis_error_raises_unauthorized() -> None:
    store = RedisSessionStore(_FakeKV(fail_ops={"getdel"}))
    with pytest.raises(UnauthorizedError):
        await store.consume_refresh("t")
