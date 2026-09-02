"""Skill Pack 域（domain/skill）：智能体包发现、清单校验、索引、装配、热重载。

AgentPackage = AGENT.md（AgentManifest）+ 其技能目录（SkillManifest）的聚合体；
manifest.py 为 frontmatter 模型，definition.py 为加载产出的聚合体，loader 只负责
「怎么加载」。解析（SkillResolver）已随「解析服务 Runtime」原则移至 runtime/resolver。
"""

from app.domain.skill.assemble import AssemblyPlan, SkillAssembler
from app.domain.skill.definition import (
    AgentLoadFailure,
    AgentPackage,
    AgentRegistrySnapshot,
    SkillLoadResult,
)
from app.domain.skill.hot_reload import HotReloader
from app.domain.skill.index import AgentIndex, AgentIndexEntry, SkillIndexEntry
from app.domain.skill.loader import AgentLoader
from app.domain.skill.manifest import (
    AgentManifest,
    DocumentDeclaration,
    GateDeclaration,
    MCPSkillDependency,
    Scope,
    ScriptDeclaration,
    SkillManifest,
    TemplateDeclaration,
)
from app.domain.skill.registry import AgentRegistry

__all__ = [
    "AgentIndex",
    "AgentIndexEntry",
    "AgentLoadFailure",
    "AgentLoader",
    "AgentManifest",
    "AgentPackage",
    "AgentRegistry",
    "AgentRegistrySnapshot",
    "AssemblyPlan",
    "DocumentDeclaration",
    "GateDeclaration",
    "HotReloader",
    "MCPSkillDependency",
    "Scope",
    "ScriptDeclaration",
    "SkillAssembler",
    "SkillIndexEntry",
    "SkillLoadResult",
    "SkillManifest",
    "TemplateDeclaration",
]
