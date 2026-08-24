"""装配层（L2）：智能体注册、清单校验、两级索引、技能装配、热重载。"""

from platform_engine.registry.assemble import AssemblyPlan, SkillAssembler
from platform_engine.registry.hot_reload import HotReloader
from platform_engine.registry.index import AgentIndex, AgentIndexEntry, SkillIndexEntry
from platform_engine.registry.loader import (
    AgentLoader,
    AgentLoadFailure,
    AgentPackage,
    AgentRegistrySnapshot,
    SkillLoadResult,
)
from platform_engine.registry.manifests import (
    AgentManifest,
    DocumentDeclaration,
    GateDeclaration,
    MCPSkillDependency,
    Scope,
    ScriptDeclaration,
    SkillManifest,
    TemplateDeclaration,
)
from platform_engine.registry.registry import AgentRegistry

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
