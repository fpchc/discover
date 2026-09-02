"""两级索引（agent-package-spec §10）：路由输入规模分层，不随平台膨胀。

一级路由只看 agents（身份 + 适用边界），不看任何技能信息；
二级路由只看选定智能体的 skills_by_agent，不看其他智能体。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.skill.definition import AgentRegistrySnapshot
from app.domain.skill.manifest import Scope


class AgentIndexEntry(BaseModel):
    """一级索引项：身份 + 类型 + 适用边界，不含技能细节。"""

    agent_id: str
    display_name: str
    type: str = "expert"
    description: str
    scope: Scope
    default_skill: str | None = None


class SkillIndexEntry(BaseModel):
    """二级路由输入：只含适用边界与触发词。"""

    skill_id: str
    description: str
    scope: Scope
    keywords: list[str] = Field(default_factory=list)


class AgentIndex(BaseModel):
    """两级索引快照。一级只看 agents；二级只看 skills_by_agent[选定智能体]。"""

    agents: dict[str, AgentIndexEntry] = Field(default_factory=dict)
    skills_by_agent: dict[str, dict[str, SkillIndexEntry]] = Field(default_factory=dict)

    @classmethod
    def from_snapshot(cls, snapshot: AgentRegistrySnapshot) -> AgentIndex:
        agents: dict[str, AgentIndexEntry] = {}
        skills_by_agent: dict[str, dict[str, SkillIndexEntry]] = {}
        for agent_id, package in snapshot.packages.items():
            agents[agent_id] = AgentIndexEntry(
                agent_id=agent_id,
                display_name=package.manifest.display_name,
                type=package.manifest.type,
                description=package.manifest.description,
                scope=package.manifest.scope,
                default_skill=package.manifest.default_skill,
            )
            skill_entries: dict[str, SkillIndexEntry] = {}
            for skill_id, skill in package.skills.items():
                skill_entries[skill_id] = SkillIndexEntry(
                    skill_id=skill_id,
                    description=skill.description,
                    scope=skill.scope,
                    keywords=skill.keywords,
                )
            skills_by_agent[agent_id] = skill_entries
        return cls(agents=agents, skills_by_agent=skills_by_agent)
