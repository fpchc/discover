"""技能包（Skill Pack）：AGENT.md / SKILL.md 的清单模型、加载、索引与装配。

AgentPackage = AGENT.md（AgentManifest）+ 其技能目录（SkillManifest）的聚合体。
技能包定义 Harness 的行为，因此与 Harness 同属一根支柱：加载（loader）、
两级索引（index）、装配计划（assemble）、运行时对齐契约（contract）、
注册表门面（registry）与热重载（hot_reload）都在本包内。
"""

from app.harness.skill.assemble import AssemblyPlan, SkillAssembler
from app.harness.skill.definition import (
    AgentLoadFailure,
    AgentPackage,
    AgentRegistrySnapshot,
    SkillLoadResult,
)
from app.harness.skill.hot_reload import HotReloader
from app.harness.skill.index import AgentIndex, AgentIndexEntry, SkillIndexEntry
from app.harness.skill.loader import AgentLoader
from app.harness.skill.manifest import (
    AgentManifest,
    DocumentDeclaration,
    GateDeclaration,
    MCPSkillDependency,
    Scope,
    ScriptDeclaration,
    SkillManifest,
    SkillWorkflowDefinition,
    TemplateDeclaration,
)
from app.harness.skill.registry import AgentRegistry

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
    "SkillWorkflowDefinition",
    "TemplateDeclaration",
]
