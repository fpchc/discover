"""智能体注册表门面（L2）：扫描、两级索引、技能装配、热重载。"""

from app.config.loader import MCPRegistry
from app.config.settings import Settings
from app.errors.base import RegistryValidationError
from app.registry.assemble import AssemblyPlan, SkillAssembler
from app.registry.index import AgentIndex
from app.registry.loader import (
    AgentLoader,
    AgentPackage,
    AgentRegistrySnapshot,
)
from app.registry.manifests import SkillManifest


class AgentRegistry:
    """智能体注册表：持有加载快照，提供两级索引与技能装配查询。"""

    def __init__(self, settings: Settings, mcp_registry: MCPRegistry) -> None:
        self._loader = AgentLoader(settings, mcp_registry)
        self._assembler = SkillAssembler(mcp_registry)
        # 归一为绝对路径：技能目录 / 脚本宿主路径 / SKILL_ROOT_DIR 一律绝对，
        # 否则脚本 subprocess cwd=工作区时会把相对脚本路径按工作区解析而找不到
        # （实测：dedup_manager 报 "No such file or directory"）。
        self._agents_root = settings.agents_root_dir.resolve()
        self._snapshot = AgentRegistrySnapshot()

    async def refresh(self) -> AgentRegistrySnapshot:
        """重扫智能体包并原子替换快照。返回本次加载结果。"""
        snapshot = await self._loader.load_agents(self._agents_root)
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

    def assemble(self, agent_id: str, skill_id: str | None) -> AssemblyPlan:
        """装配技能上下文；skill_id 缺省取智能体默认技能。"""
        package = self.get_agent(agent_id)
        if package is None:
            raise RegistryValidationError(f"未知智能体：{agent_id}")
        return self._assembler.assemble(package, skill_id)
