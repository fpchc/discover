"""工具激活计划（环境侧端口形状）。

单一动机：**断开 harness ⇄ environment 双向依赖**。工具激活需要「技能装配的
结论」（要起哪些 MCP、注册哪些脚本），但那套结论由 harness 产出——若环境直接
引用 harness 的 `AssemblyPlan`，两根支柱就互相依赖。

因此环境只声明自己需要的形状（本模块），harness 的技能装配负责把
`AssemblyPlan` 投影成 `ToolActivationPlan`（`AssemblyPlan.tool_plan()`），
依赖方向固定为 harness → environment。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.config.settings import SideEffectType


class ScriptSpec(BaseModel):
    """技能白名单脚本在环境侧的最小声明（供 ToolBroker 注册脚本工具）。"""

    path: str
    name: str
    description: str
    schema_path: str | None = None
    timeout_seconds: float | None = None
    side_effect: SideEffectType = SideEffectType.READ_ONLY


class CapabilitySpec(BaseModel):
    """平台能力在环境侧的装配说明（failover / all 两种策略）。"""

    capability: str
    strategy: Literal["failover", "all"] = "failover"
    candidate_servers: list[str] = Field(default_factory=list)
    core_tools: list[str] = Field(default_factory=list)
    required: bool = True
    degrade_note: str | None = None
    fallback_capability: str | None = None
    fallback_servers: list[str] = Field(default_factory=list)


class ToolActivationPlan(BaseModel):
    """一次激活所需的全部环境侧信息（ToolBroker.activate 的唯一入参）。"""

    agent_id: str
    skill_id: str
    required_mcp_servers: list[str] = Field(default_factory=list)
    optional_mcp_servers: list[str] = Field(default_factory=list)
    mcp_degrade_notes: dict[str, str] = Field(default_factory=dict)
    capabilities: list[CapabilitySpec] = Field(default_factory=list)
    core_tool_names: list[str] = Field(default_factory=list)
    scripts: list[ScriptSpec] = Field(default_factory=list)
    env_whitelist: list[str] = Field(default_factory=list)


__all__ = ["CapabilitySpec", "ScriptSpec", "ToolActivationPlan"]
