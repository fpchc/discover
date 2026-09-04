"""Workflow 定义模型（react-runtime-v2-architecture §9）。

单一动机：把阶段编排从 Skill Pack 的 Markdown 正文提升为机器可读的
WorkflowDefinition / PhaseDefinition。平台只解释通用结构（§5.5），
不包含具体 Agent / Skill 业务字面量。

阶段类型（§9.2）：react / script / tool / contract / transform / render，
具体阶段名称与业务含义由 Skill Pack 声明，平台经 executors 注册表解释。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class PhaseExecutorType(StrEnum):
    """阶段执行器类型（§9.2）。"""

    REACT = "react"
    SCRIPT = "script"
    TOOL = "tool"
    CONTRACT = "contract"
    TRANSFORM = "transform"
    RENDER = "render"


class PhaseDefinition(BaseModel):
    """阶段定义：输入 schema、执行器、允许工具、预算、Contract、fallback。"""

    phase_id: str
    executor_type: PhaseExecutorType = PhaseExecutorType.REACT
    goal: str = ""
    input_schema: dict[str, object] = Field(default_factory=dict)
    output_schema: dict[str, object] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    contract_refs: list[str] = Field(default_factory=list)
    fallback_phase: str | None = None
    # 输入绑定：`input_bindings` 映射 `phase_id.field → 本阶段字段名`（§9.4 只读绑定）。
    # 键为上游 PhaseOutput 的字段路径，值为本阶段输入字段名。
    input_bindings: dict[str, str] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    """Workflow 定义：阶段清单 + 输出 Contract（§9.1/§9.2）。

    平台经编译期将本定义编译为 LangGraph 图（节点 + 条件边），
    阶段推进不依赖自然语言（§23.6）。
    """

    workflow_id: str
    phases: list[PhaseDefinition] = Field(default_factory=list)
    output_contract_refs: list[str] = Field(default_factory=list)
