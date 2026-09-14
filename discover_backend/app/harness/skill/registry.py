"""智能体注册表门面（L2）：扫描、两级索引、技能装配、热重载。"""

from app.config.loader import MCPRegistry
from app.config.settings import Settings
from app.harness.skill.assemble import AssemblyPlan, SkillAssembler
from app.harness.skill.definition import AgentPackage, AgentRegistrySnapshot
from app.harness.skill.index import AgentIndex
from app.harness.skill.loader import AgentLoader
from app.harness.skill.manifest import SkillManifest
from app.harness.skill.source import AgentPackageSource, FileSystemPackageSource
from app.shared.errors.base import RegistryValidationError


class AgentRegistry:
    """智能体注册表：持有加载快照，提供两级索引与技能装配查询。"""

    def __init__(
        self,
        settings: Settings,
        mcp_registry: MCPRegistry,
        source: AgentPackageSource | None = None,
    ) -> None:
        self._assembler = SkillAssembler(mcp_registry)
        self._source = source or FileSystemPackageSource(
            AgentLoader(settings, mcp_registry), settings.agents_root_dir.resolve()
        )
        self._snapshot = AgentRegistrySnapshot()

    async def refresh(self) -> AgentRegistrySnapshot:
        """重扫技能包并原子替换快照。返回本次加载结果。"""
        snapshot = await self._source.load_all()
        self._snapshot = snapshot
        return snapshot

    @property
    def snapshot(self) -> AgentRegistrySnapshot:
        return self._snapshot

    def index(self) -> AgentIndex:
        """两级路由索引（一级智能体 / 二级技能）。"""
        return AgentIndex.from_snapshot(self._snapshot)

    def get_agent(self, agent_id: str) -> AgentPackage | None:
        return self._snapshot.packages.get(agent_id)

    def get_skill(self, agent_id: str, skill_id: str) -> SkillManifest | None:
        package = self.get_agent(agent_id)
        if package is None:
            return None
        return package.skills.get(skill_id)

    def assemble_package(self, package: AgentPackage, skill_id: str | None) -> AssemblyPlan:
        """装配一个已加载的智能体包（草稿预览/调试路径直接注入包）。"""
        return self._assembler.assemble(package, skill_id)

    def assemble(self, agent_id: str, skill_id: str | None) -> AssemblyPlan:
        """装配技能上下文；skill_id 缺省取智能体默认技能。"""
        package = self.get_agent(agent_id)
        if package is None:
            raise RegistryValidationError(f"未知智能体：{agent_id}")
        return self._assembler.assemble(package, skill_id)
