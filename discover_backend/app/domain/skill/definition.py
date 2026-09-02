"""Skill Pack 定义（domain/skill）：加载产出的聚合体与快照。

AgentPackage = 已校验通过的智能体包（manifest + skills 聚合体）；加载失败项
与一次扫描快照一并在此。loader 只负责「怎么加载」，不持有定义（§13.1 单一动机）。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.domain.skill.manifest import AgentManifest, SkillManifest


class SkillLoadResult(BaseModel):
    """单个技能加载结果（无效原因对前端暴露，便于排查）。"""

    skill_id: str
    ok: bool
    invalid_reason: str | None = None


class AgentPackage(BaseModel):
    """已加载并校验通过的智能体包（含全部有效技能与技能级失败项）。"""

    root: Path
    manifest: AgentManifest
    skills: dict[str, SkillManifest] = Field(default_factory=dict)
    skill_failures: list[SkillLoadResult] = Field(default_factory=list)


class AgentLoadFailure(BaseModel):
    """单个智能体加载失败项（不影响其他智能体）。"""

    agent_id: str
    reason: str


class AgentRegistrySnapshot(BaseModel):
    """一次扫描的完整结果：成功包 + 失败项。"""

    packages: dict[str, AgentPackage] = Field(default_factory=dict)
    failures: list[AgentLoadFailure] = Field(default_factory=list)
