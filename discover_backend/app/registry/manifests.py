"""AGENT / SKILL 清单模型（agent-package-spec §2-§7）。

清单 = YAML frontmatter（结构化元信息）+ 正文（行为约束 / 工作流）。
字段与规范一一对应；frontmatter 解析与加载期校验见 loader.py。
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.config.settings import SideEffectType

ThinkingPreference = Literal["off", "low", "medium", "high"]


class Scope(BaseModel):
    """适用边界：一级 / 二级路由的主要依据，须同时写「适用」与「不适用」。"""

    applies: str
    does_not_apply: str


class MCPSkillDependency(BaseModel):
    """技能对 MCP 服务器的依赖声明（§4）。

    用于单服务器专有数据源（如天眼查 / 企查查），直接点名具体服务；
    多提供方可互换的搜索类通道走 CapabilityDependency。
    """

    server: str
    core_tools: list[str] = Field(default_factory=list)
    required: bool = True
    degrade_note: str | None = None


class CapabilityDependency(BaseModel):
    """技能对平台能力（而非具体 MCP 服务器）的依赖声明（§4）。

    capability 须存在于 MCP 注册表 capabilities 段；具体由哪些提供方供给、
    如何主备切换均由注册表决定，技能不点名提供方。
    """

    capability: str
    core_tools: list[str] = Field(default_factory=list)
    required: bool = True
    degrade_note: str | None = None


class ScriptDeclaration(BaseModel):
    """技能白名单脚本声明（§5）。工具名在所属技能内唯一。"""

    path: str
    name: str
    description: str
    schema_path: str | None = None
    timeout_seconds: float | None = None
    side_effect: SideEffectType = SideEffectType.READ_ONLY
    history_store: bool = False


class DocumentDeclaration(BaseModel):
    """参考文档声明（§6）。默认不预加载。"""

    path: str
    when: str
    preload: bool = False


class GateDeclaration(BaseModel):
    """门禁声明（§7）。能写校验器的门禁不要只写成提示词。"""

    id: str
    condition: str
    validator: str | None = None
    schema_path: str | None = None
    blocking: bool = True


class TemplateDeclaration(BaseModel):
    """模板声明（§3）。"""

    path: str
    purpose: str


class AgentManifest(BaseModel):
    """一级清单（AGENT.md）：智能体身份、全局约束、技能索引。

    kind 描述「清单是什么」：当前仅 agent（专家智能体包）；skill/workflow 属
    未来独立 kind，不是 agent 类型。type 描述 agent 下的细分（expert）。
    """

    kind: Literal["agent"] = "agent"
    type: Literal["expert"] = "expert"
    agent_id: str
    display_name: str
    version: str
    description: str
    scope: Scope
    default_skill: str | None = None
    model_preference: str | None = None
    thinking_preference: ThinkingPreference | None = None
    env_whitelist: list[str] = Field(default_factory=list)
    skills: list[str]
    body: str = ""


class SkillManifest(BaseModel):
    """二级清单（SKILL.md）：技能适用边界、依赖声明、工作流正文。"""

    skill_id: str
    version: str
    description: str
    scope: Scope
    keywords: list[str] = Field(default_factory=list)
    mcp_dependencies: list[MCPSkillDependency] = Field(default_factory=list)
    capability_dependencies: list[CapabilityDependency] = Field(default_factory=list)
    scripts: list[ScriptDeclaration] = Field(default_factory=list)
    documents: list[DocumentDeclaration] = Field(default_factory=list)
    gates: list[GateDeclaration] = Field(default_factory=list)
    templates: list[TemplateDeclaration] = Field(default_factory=list)
    body: str = ""
