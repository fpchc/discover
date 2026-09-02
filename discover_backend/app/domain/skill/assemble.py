"""技能装配（L2，platform-architecture §6）：注入智能体全局约束 + 技能工作流。

装配产出的上下文是清单正文（智能体约束 / 技能工作流 / 文档清单 / 模板 / 门禁），
流程控制仍由图与脚本承担，不写成自然语言提示词（红线 §4）。
"""

import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.config.loader import MCPRegistry
from app.config.settings import SideEffectType
from app.domain.skill.definition import AgentPackage
from app.domain.skill.manifest import (
    AgentManifest,
    ScriptDeclaration,
    SkillManifest,
    ThinkingPreference,
)
from app.shared.errors.base import RegistryValidationError

logger = logging.getLogger(__name__)


class CapabilityPlan(BaseModel):
    """能力装配计划。

    strategy="failover"（默认）：按候选服务器顺序主备切换，第一个可用者生效。
    strategy="all"：全部候选各自激活为独立工具，调用哪个由模型（re-act）决定，
    不做切换也不做降级——用于多搜索提供方并存场景。

    能力级降级（注册表 `MCSCapability.fallback`）：主候选全部不可用时，装配层
    解析 fallback 能力的候选服务器（fallback_servers）随计划下发；代理层命中后
    视为「已降级至 fallback 能力」，降级说明由系统生成，不来自技能清单。
    strategy="all" 时忽略 fallback。
    """

    capability: str
    strategy: Literal["failover", "all"] = "failover"
    candidate_servers: list[str] = Field(default_factory=list)
    core_tools: list[str] = Field(default_factory=list)
    required: bool = True
    degrade_note: str | None = None
    fallback_capability: str | None = None
    fallback_servers: list[str] = Field(default_factory=list)


class AssemblyPlan(BaseModel):
    """技能装配计划：运行时据此装配工具、注入上下文、启动 MCP 依赖。"""

    agent_id: str
    skill_id: str
    system_prompt: str
    required_mcp_servers: list[str] = Field(default_factory=list)
    optional_mcp_servers: list[str] = Field(default_factory=list)
    mcp_degrade_notes: dict[str, str] = Field(default_factory=dict)
    capabilities: list[CapabilityPlan] = Field(default_factory=list)
    core_tool_names: list[str] = Field(default_factory=list)
    scripts: list[ScriptDeclaration] = Field(default_factory=list)
    env_whitelist: list[str] = Field(default_factory=list)
    model_preference: str | None = None
    thinking_preference: ThinkingPreference | None = None


def _gate_validator_scripts(skill: SkillManifest) -> list[ScriptDeclaration]:
    """把有校验器的门禁注册为脚本工具 `<agent>.<skill>.script.gate_<id>`。

    graph-runtime-spec §6：校验器即脚本工具，模型调用后由 tool_node 写门禁状态。
    无校验器的门禁保持提示词自检（弱门禁）。
    """
    declarations: list[ScriptDeclaration] = []
    for gate in skill.gates:
        if gate.validator is None:
            continue
        declarations.append(
            ScriptDeclaration(
                path=gate.validator,
                name=f"gate_{gate.id}",
                description=f"门禁校验：{gate.condition}",
                schema_path=gate.schema_path,
                side_effect=SideEffectType.READ_ONLY,
            )
        )
    return declarations


def _build_system_prompt(agent: AgentManifest, skill: SkillManifest) -> str:
    sections: list[str] = [
        f"# 智能体：{agent.display_name}",
        agent.body,
        f"# 技能：{skill.description}",
        skill.body,
    ]
    if skill.documents:
        doc_lines = "\n".join(f"- {doc.path}：{doc.when}" for doc in skill.documents)
        sections.append(f"# 参考文档（按需读取）\n{doc_lines}")
    if skill.templates:
        tmpl_lines = "\n".join(
            f"- {template.path}：{template.purpose}" for template in skill.templates
        )
        sections.append(f"# 模板\n{tmpl_lines}")
    if skill.gates:
        gate_lines = "\n".join(f"- {gate.id}：{gate.condition}" for gate in skill.gates)
        sections.append(f"# 门禁\n{gate_lines}")
    sections.append(
        "# 平台红线（强制）\n"
        "- 涉及智能体身份时一律使用展示名（display_name）。\n"
        "- 思考过程与可见回答中，严禁出现内部 agent_id / 智能体标识字符串"
        "（如包名、目录名、工具命名空间前缀等）。"
    )
    return "\n\n".join(sections)


class SkillAssembler:
    """在选定智能体内部选技能、装配上下文与工具声明。

    依赖 MCP 注册表：把技能声明的能力解析为候选服务器列表（failover），
    技能本身不点名提供方。
    """

    def __init__(self, mcp_registry: MCPRegistry) -> None:
        self._mcp_registry = mcp_registry

    def assemble(self, package: AgentPackage, skill_id: str | None) -> AssemblyPlan:
        skill = self._resolve_skill(package, skill_id)
        required: list[str] = []
        optional: list[str] = []
        degrade_notes: dict[str, str] = {}
        core_tool_names: list[str] = []
        for dep in skill.mcp_dependencies:
            core_tool_names.extend(dep.core_tools)
            if not self._mcp_registry.server_enabled(dep.server):
                logger.info("MCP 服务 %s 已显式禁用（enabled: false），跳过装配", dep.server)
                continue
            if dep.required:
                required.append(dep.server)
            else:
                optional.append(dep.server)
                if dep.degrade_note:
                    degrade_notes[dep.server] = dep.degrade_note
        capabilities = self._resolve_capabilities(skill)
        scripts = skill.scripts + _gate_validator_scripts(skill)
        return AssemblyPlan(
            agent_id=package.manifest.agent_id,
            skill_id=skill.skill_id,
            system_prompt=_build_system_prompt(package.manifest, skill),
            required_mcp_servers=required,
            optional_mcp_servers=optional,
            mcp_degrade_notes=degrade_notes,
            capabilities=capabilities,
            core_tool_names=core_tool_names,
            scripts=scripts,
            env_whitelist=package.manifest.env_whitelist,
            model_preference=package.manifest.model_preference,
            thinking_preference=package.manifest.thinking_preference,
        )

    def _resolve_capabilities(self, skill: SkillManifest) -> list[CapabilityPlan]:
        plans: list[CapabilityPlan] = []
        for dep in skill.capability_dependencies:
            capability = self._mcp_registry.capabilities.get(dep.capability)
            if capability is None:
                raise RegistryValidationError(f"平台能力未注册：{dep.capability}")
            fallback_capability = capability.fallback
            fallback_servers: list[str] = []
            if fallback_capability is not None:
                fallback = self._mcp_registry.capabilities.get(fallback_capability)
                if fallback is None:
                    raise RegistryValidationError(f"能力降级目标未注册：{fallback_capability}")
                fallback_servers = [
                    sid for sid in fallback.servers if self._mcp_registry.server_enabled(sid)
                ]
            plans.append(
                CapabilityPlan(
                    capability=dep.capability,
                    strategy=capability.strategy,
                    candidate_servers=[
                        sid for sid in capability.servers if self._mcp_registry.server_enabled(sid)
                    ],
                    core_tools=dep.core_tools,
                    required=dep.required,
                    degrade_note=dep.degrade_note,
                    fallback_capability=fallback_capability,
                    fallback_servers=fallback_servers,
                )
            )
        return plans

    @staticmethod
    def _resolve_skill(package: AgentPackage, skill_id: str | None) -> SkillManifest:
        if skill_id is None:
            if package.manifest.default_skill is None:
                raise RegistryValidationError(f"智能体 {package.manifest.agent_id} 未声明默认技能")
            skill_id = package.manifest.default_skill
        skill = package.skills.get(skill_id)
        if skill is None:
            raise RegistryValidationError(f"技能不可用：{skill_id}")
        return skill
