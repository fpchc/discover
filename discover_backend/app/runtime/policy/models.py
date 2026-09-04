"""Policy 决策模型（react-runtime-v2-architecture §11.2）。

单一动机：Policy 结果为结构化枚举，不使用自由文本控制流程（§5.2「LLM 只有建议权、
Engine 拥有控制权」）。PolicyDecision 携带 reason code、面向用户的展示说明、
重试 / 降级 / 预算快照，供 Workflow 与 ReAct 子图做确定性分支。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from app.runtime.models import BudgetState


class PolicyDecisionType(StrEnum):
    """Policy 决策类型（§11.2 七种结构化枚举）。"""

    ALLOW = "allow"
    RETRY = "retry"
    SKIP = "skip"
    DEGRADE = "degrade"
    FINALIZE_PARTIAL = "finalize_partial"
    TERMINATE = "terminate"
    FAIL = "fail"


class PolicyDecision(BaseModel):
    """Policy 判定结果：结构化决策 + 原因 + 展示信息 + 恢复/降级指引。"""

    decision: PolicyDecisionType
    reason_code: str = ""
    display_message: str = ""
    retry_delay_seconds: float | None = None
    attempt: int = 0
    fallback_phase: str | None = None
    budget_snapshot: BudgetState | None = None
    recoverable: bool = True
