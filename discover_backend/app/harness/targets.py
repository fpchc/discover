"""助手选择域模型（catalog / runtime / session 共享，跨边界 pydantic）。

用户选择的是一个「助手目标」：专家（expert，来自 agents/ 包）或通用（generic，
内置通用对话）。skill 属未来独立 kind，不在此枚举扩展（不是 agent 类型）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

# 内置通用助手的保留 id / 显示名（目录合成项；专家包不得占用该 id）。
GENERIC_ASSISTANT_ID = "generic"
GENERIC_ASSISTANT_NAME = "通用对话"


class TargetType(StrEnum):
    """助手目标类型。"""

    EXPERT = "expert"
    GENERIC = "generic"
    SKILL = "skill"  # future：简单技能（天气等 prompt 型），非本次实现


class SelectionSource(StrEnum):
    """选择来源（事件审计用）。"""

    USER = "user"
    SYSTEM = "system"
    WORKFLOW = "workflow"  # future
    POLICY = "policy"  # future


class AssistantTarget(BaseModel):
    """助手目标：类型 + id。

    expert → id 为智能体 ID；generic/skill → id 为空。
    runtime 只感知该模型，不感知 wire 层字符串。
    """

    type: TargetType
    id: str | None = None
