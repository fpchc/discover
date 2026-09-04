"""Observation Policy（react-runtime-v2-architecture §11.1）。

单一动机：工具结果归一后判定——返回是否为空、是否重复相同结果/错误、是否产生
新证据或产物、是否应切换数据源或进入降级。Policy 不执行工具、不决定阶段完成，
只产出结构化决策供 ReAct 子图路由（§21 职责边界）。
"""

from __future__ import annotations

from app.runtime.models import ObservationRecord, ObservationStatus, ProgressState
from app.runtime.policy.models import PolicyDecision, PolicyDecisionType
from app.shared.errors.base import ErrorCategory


def check_observation(
    *,
    observation: ObservationRecord,
    progress: ProgressState,
    repeat_threshold: int,
) -> PolicyDecision:
    """工具结果判定（§11.1 Observation Policy）。

    EMPTY → RETRY（无返回）；重复相同错误 → DEGRADE（建议换源）；重复相同结果
    → 计入无进展（由 progress 判定）；有产物/新证据 → ALLOW。
    """
    if observation.status == ObservationStatus.EMPTY:
        return PolicyDecision(
            decision=PolicyDecisionType.RETRY,
            reason_code="empty_observation",
            display_message="工具返回为空，重试或换用其他工具",
            recoverable=True,
        )
    if observation.status == ObservationStatus.DUPLICATE:
        return PolicyDecision(
            decision=PolicyDecisionType.FINALIZE_PARTIAL
            if progress.consecutive_no_progress >= repeat_threshold
            else PolicyDecisionType.ALLOW,
            reason_code="duplicate_observation",
            display_message="工具返回与之前重复",
            recoverable=True,
        )
    if (
        observation.status == ObservationStatus.FAILED
        and observation.error_category == ErrorCategory.SERVER
    ):
        return PolicyDecision(
            decision=PolicyDecisionType.DEGRADE,
            reason_code="observation_server_error",
            display_message="数据源服务错误，切换备用通道",
            recoverable=True,
        )
    return PolicyDecision(decision=PolicyDecisionType.ALLOW, reason_code="ok")
