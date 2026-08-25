"""插件管理器单测：启停开关、require 类型收窄、启停顺序、内置插件默认顺序。

测试用桩插件写入全局 PLUGIN_REGISTRY，fixture 负责恢复现场，避免污染
真实插件注册表。
"""

import pytest
from app.config.settings import Settings
from app.errors.base import ConfigError
from app.plugins import PluginManager
from app.plugins.base import PLUGIN_REGISTRY, Plugin

# 启停顺序断言用的共享事件记录（桩插件静态引用）。
_EVENTS: list[str] = []


class StubA(Plugin):
    """桩插件 A。"""

    name = "stub_a"

    async def startup(self) -> None:
        _EVENTS.append("a:start")

    async def shutdown(self) -> None:
        _EVENTS.append("a:shutdown")


class StubB(Plugin):
    """桩插件 B。"""

    name = "stub_b"

    async def startup(self) -> None:
        _EVENTS.append("b:start")

    async def shutdown(self) -> None:
        _EVENTS.append("b:shutdown")


class StubDisabled(Plugin):
    """默认禁用的桩插件。"""

    name = "stub_off"

    @classmethod
    def is_enabled(cls, settings: Settings) -> bool:
        return False

    async def startup(self) -> None:
        _EVENTS.append("off:start")

    async def shutdown(self) -> None:
        _EVENTS.append("off:shutdown")


@pytest.fixture()
def clean_registry() -> None:
    """备份并清空 PLUGIN_REGISTRY，测试后恢复。"""
    saved = dict(PLUGIN_REGISTRY)
    PLUGIN_REGISTRY.clear()
    yield
    PLUGIN_REGISTRY.clear()
    PLUGIN_REGISTRY.update(saved)


def _settings() -> Settings:
    return Settings(_env_file=None)


async def test_startup_then_shutdown_reverse_order(clean_registry: None) -> None:
    PLUGIN_REGISTRY["stub_a"] = StubA
    PLUGIN_REGISTRY["stub_b"] = StubB
    manager = PluginManager(_settings())
    _EVENTS.clear()
    await manager.startup()
    assert _EVENTS == ["a:start", "b:start"]
    await manager.shutdown()
    assert _EVENTS == ["a:start", "b:start", "b:shutdown", "a:shutdown"]


async def test_disabled_plugin_not_started(clean_registry: None) -> None:
    PLUGIN_REGISTRY["stub_a"] = StubA
    PLUGIN_REGISTRY["stub_off"] = StubDisabled
    manager = PluginManager(_settings())
    assert manager.enabled_names == ("stub_a",)
    _EVENTS.clear()
    await manager.startup()
    assert _EVENTS == ["a:start"]


def test_require_returns_same_typed_instance(clean_registry: None) -> None:
    PLUGIN_REGISTRY["stub_a"] = StubA
    manager = PluginManager(_settings())
    first = manager.require(StubA)
    second = manager.require(StubA)
    assert first is second
    assert isinstance(first, StubA)


def test_require_disabled_raises_config_error(clean_registry: None) -> None:
    PLUGIN_REGISTRY["stub_off"] = StubDisabled
    manager = PluginManager(_settings())
    with pytest.raises(ConfigError):
        manager.require(StubDisabled)


def test_require_unknown_raises_config_error(clean_registry: None) -> None:
    manager = PluginManager(_settings())
    with pytest.raises(ConfigError):
        manager.require(StubA)


def test_builtin_order_logging_first_and_redis_default_off() -> None:
    """真实注册表：logging 最先，redis 默认关闭。"""
    manager = PluginManager(_settings())
    assert manager.enabled_names == ("logging", "db", "storage", "mcp", "llm")
