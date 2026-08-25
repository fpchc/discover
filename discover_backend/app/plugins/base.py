"""插件系统基座：Plugin ABC + 注册表 + PluginManager。

基础设施能力以插件形式统一加载：每个插件 = 配置开关（{name}_enabled，
由 is_enabled 读取类型化 Settings 字段）+ 生命周期（startup/shutdown）
+ 类型化客户端访问（require）。注册顺序即启动顺序，关停逆序。

依赖方向：container → plugins → 现有底层模块（db/storage/tools/mcp/llm）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.config.settings import Settings
from app.errors.base import ConfigError

# 按声明顺序登记的插件类；容器 import app.plugins 时经 @register 填充。
PLUGIN_REGISTRY: dict[str, type[Plugin]] = {}


class Plugin(ABC):
    """基础设施插件基类。

    子类必须声明唯一 name（与配置开关前缀 {name}_enabled 对应），并实现
    startup / shutdown。具体客户端经 require() 收窄访问。
    """

    name: str

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @classmethod
    def is_enabled(cls, settings: Settings) -> bool:
        """是否启用。子类覆盖为读取自己的类型化字段（如 settings.redis_enabled）。"""
        return True

    @abstractmethod
    async def startup(self) -> None:
        """开启能力：建连 / 加载配置。"""

    @abstractmethod
    async def shutdown(self) -> None:
        """释放能力：断开 / 关连接。"""


def register[P: Plugin](cls: type[P]) -> type[P]:
    """类装饰器：按类声明的 name 登记到 PLUGIN_REGISTRY。"""
    name = cls.name
    if name in PLUGIN_REGISTRY:
        raise ValueError(f"插件重名注册：{name}")
    PLUGIN_REGISTRY[name] = cls
    return cls


class PluginManager:
    """插件管理器：按声明顺序实例化启用插件，统一启停，类型安全取客户端。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._plugins: dict[str, Plugin] = {}
        for name, cls in PLUGIN_REGISTRY.items():
            if cls.is_enabled(settings):
                self._plugins[name] = cls(settings)

    @property
    def enabled_names(self) -> tuple[str, ...]:
        """已启用插件名（声明顺序）。"""
        return tuple(self._plugins)

    def require[P: Plugin](self, plugin_type: type[P]) -> P:
        """取类型化插件实例；未启用或类型不符抛 ConfigError。"""
        plugin = self._plugins.get(plugin_type.name)
        if plugin is None:
            raise ConfigError(f"插件未启用：{plugin_type.name}")
        if not isinstance(plugin, plugin_type):
            raise ConfigError(f"插件类型不匹配：{plugin_type.name}")
        return plugin

    async def startup(self) -> None:
        """按声明顺序启动全部已启用插件。"""
        for plugin in self._plugins.values():
            await plugin.startup()

    async def shutdown(self) -> None:
        """逆序关闭全部已启用插件。"""
        for plugin in reversed(tuple(self._plugins.values())):
            await plugin.shutdown()
