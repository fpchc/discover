"""热重载（agent-package-spec §10）：配置开关、快照语义、后台轮询。

开关关闭时 run() 立即返回。快照整体原子替换；进行中会话已装配的
清单是快照内的不可变对象，不因重载改变（会话内保持快照语义）。
"""

import anyio

from platform_engine.config.settings import Settings
from platform_engine.registry.registry import AgentRegistry


class HotReloader:
    """后台热重载：按间隔重扫智能体包并替换快照。"""

    def __init__(self, registry: AgentRegistry, settings: Settings) -> None:
        self._registry = registry
        self._enabled = settings.hot_reload_enabled
        self._interval_seconds = settings.hot_reload_interval_seconds

    async def run(self) -> None:
        """后台循环；取消（CancelledError）或开关关闭即结束。"""
        if not self._enabled:
            return
        while True:
            await anyio.sleep(self._interval_seconds)
            await self._registry.refresh()
