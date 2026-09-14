"""数据库技能包源：已发布 bundle 物化后复用 AgentLoader 校验加载。

依赖方向 application → harness：Source 端口由 harness 定义，本实现属于业务侧
适配器（组合根注入）。未发布的智能体回落到代码包（filesystem），保证首启 /
未发布前仍可用。
"""

from __future__ import annotations

from pathlib import Path

from app.application.skill_package.service import SkillPackageService
from app.harness.skill.definition import AgentLoadFailure, AgentRegistrySnapshot
from app.harness.skill.loader import AgentLoader
from app.shared.errors.base import RegistryValidationError


class DatabasePackageSource:
    """以数据库已发布版本为准、文件系统代码包为底座的技能包源。"""

    def __init__(
        self,
        loader: AgentLoader,
        packages: SkillPackageService,
        agents_root: Path,
    ) -> None:
        self._loader = loader
        self._packages = packages
        self._agents_root = agents_root

    async def load_all(self) -> AgentRegistrySnapshot:
        """先加载代码包快照，再用数据库已发布版本逐 agent 覆盖。"""
        snapshot = await self._loader.load_agents(self._agents_root)
        published = await self._packages.list_published()
        for package in published:
            try:
                materialized = await self._packages.materialize(package)
                loaded = await self._loader.load_package_dir(materialized)
            except (RegistryValidationError, ValueError, OSError) as exc:
                snapshot.failures.append(
                    AgentLoadFailure(agent_id=package.agent_id, reason=str(exc))
                )
                snapshot.packages.pop(package.agent_id, None)
                continue
            snapshot.packages[package.agent_id] = loaded
            snapshot.failures = [
                item for item in snapshot.failures if item.agent_id != package.agent_id
            ]
        return snapshot


__all__ = ["DatabasePackageSource"]
