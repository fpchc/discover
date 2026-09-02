"""扩展加载单测：is_enabled 门控、init/startup/shutdown 顺序。

以桩扩展替换 app.bootstrap.extensions.EXTENSIONS 验证加载器逻辑；真实扩展的默认
顺序（logging 最先 / redis 默认关闭）单独断言。
"""

from types import SimpleNamespace

import pytest
from app.bootstrap.extensions import (
    EXTENSIONS,
    initialize_extensions,
    shutdown_extensions,
    startup_extensions,
)
from app.config.settings import Settings

_EVENTS: list[str] = []


class _StubExtension:
    """桩扩展：记录生命周期事件。"""

    def __init__(self, name: str, *, enabled: bool = True) -> None:
        self._name = name
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def init_app(self, app: object) -> None:
        _EVENTS.append(f"{self._name}:init")

    async def startup(self, app: object) -> None:
        _EVENTS.append(f"{self._name}:start")

    async def shutdown(self, app: object) -> None:
        _EVENTS.append(f"{self._name}:shutdown")


def _fake_app() -> SimpleNamespace:
    """带 .state 命名空间的假应用。"""
    app = SimpleNamespace()
    app.state = SimpleNamespace()
    return app


def test_initialize_gates_disabled_and_orders_init(monkeypatch: pytest.MonkeyPatch) -> None:
    enabled = _StubExtension("a")
    disabled = _StubExtension("b", enabled=False)
    tail = _StubExtension("c")
    monkeypatch.setattr("app.bootstrap.extensions.EXTENSIONS", (enabled, disabled, tail))
    app = _fake_app()
    _EVENTS.clear()
    initialize_extensions(app, settings=Settings(_env_file=None))
    assert list(app.state.enabled_extensions) == [enabled, tail]
    assert _EVENTS == ["a:init", "c:init"]


async def test_startup_then_shutdown_reverse(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _StubExtension("a")
    second = _StubExtension("b")
    monkeypatch.setattr("app.bootstrap.extensions.EXTENSIONS", (first, second))
    app = _fake_app()
    initialize_extensions(app, settings=Settings(_env_file=None))
    _EVENTS.clear()
    await startup_extensions(app)
    assert _EVENTS == ["a:start", "b:start"]
    await shutdown_extensions(app)
    assert _EVENTS == ["a:start", "b:start", "b:shutdown", "a:shutdown"]


def test_builtin_order_logging_first_redis_enabled() -> None:
    """真实扩展默认顺序：logging 最先；redis 恒启用（认证会话层硬依赖，无开关）。

    关闭日志扩展（logging_enabled=False），避免其替换根 logger 破坏本测试
    进程的日志捕获。
    """
    app = _fake_app()
    initialize_extensions(app, settings=Settings(_env_file=None, logging_enabled=False))
    names = [ext.__name__ for ext in app.state.enabled_extensions]
    assert names == [
        "app.infrastructure.database.accessors",
        "app.infrastructure.storage.accessors",
        "app.infrastructure.redis.client",
        "app.capabilities.mcp.accessors",
        "app.capabilities.llm.accessors",
    ]


def test_extensions_tuple_logging_first() -> None:
    """注册顺序即启动顺序：logging 必须在最前。"""
    assert EXTENSIONS[0].__name__ == "app.infrastructure.logging.accessors"
