"""Agent 执行内核（runtime）：状态机（engine/transition）、回合（turn）、
上下文（context/state）、解析（resolver）、执行（execution）、事件（events）。
"""

from app.runtime.engine import Runtime
from app.runtime.execution import Action, Observation, ToolExecutionOutcome, ToolExecutor
from app.runtime.resolver import (
    AssistantResolver,
    ExplicitSelectionResolver,
    SkillResolutionContext,
    SkillResolver,
    SkillStrategy,
)
from app.runtime.state import GateStatus, GraphState
from app.runtime.transition import build_graph

__all__ = [
    "Action",
    "AssistantResolver",
    "ExplicitSelectionResolver",
    "GateStatus",
    "GraphState",
    "Observation",
    "Runtime",
    "SkillResolutionContext",
    "SkillResolver",
    "SkillStrategy",
    "ToolExecutionOutcome",
    "ToolExecutor",
    "build_graph",
]
