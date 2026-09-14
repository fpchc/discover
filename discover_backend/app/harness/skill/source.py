"""技能包源端口与文件系统实现。

AgentRegistry.refresh() 只依赖本端口的 load_all()；具体来源（文件系统 / 数据库）
由组合根注入，保持 registry 与来源解耦。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.harness.skill.definition import AgentRegistrySnapshot
from app.harness.skill.loader import AgentLoader


class AgentPackageSource(Protocol):
    """技能包来源端口：一次加载返回完整快照。"""

    async def load_all(self) -> AgentRegistrySnapshot: ...


class FileSystemPackageSource:
    """本地 agents/ 目录实现（默认，单机 / 开发）。"""

    def __init__(self, loader: AgentLoader, agents_root: Path) -> None:
        self._loader = loader
        self._agents_root = agents_root

    async def load_all(self) -> AgentRegistrySnapshot:
        return await self._loader.load_agents(self._agents_root)


__all__ = ["AgentPackageSource", "FileSystemPackageSource"]
