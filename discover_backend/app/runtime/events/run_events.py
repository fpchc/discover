"""Run 生命周期事件集（react-runtime-v2-architecture §17）。

单一动机：Runtime 对 HTTP/SSE、审计与观测的统一输出。每个事件携带
run_id / step_id / sequence / phase_id 与「可展示信息 / 内部 reason code」分离字段。
高频运行事件用于实时观测，不等同于 Checkpoint；断线后不承诺重放全部高频事件（§16.1）。

终态事件契约（§17.1）：RunCompleted（SUCCEEDED|PARTIAL）表达正常完成类终态；
RunFailed 只表达无可交付结果；RunCancelled 单独表达取消。SSE 不得通过「队列为空」
猜测结束。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.runtime.contracts.models import ContractType, ContractVerdict
from app.runtime.models import (
    BudgetState,
    PhaseExecutionOutcomeType,
    PhaseStatus,
    RunStatus,
    TerminationReason,
)
from app.shared.errors.base import ErrorCategory


class RunEvent(BaseModel):
    """Run 事件基类。seq 由发射器统一分配（活跃执行期单调递增）。"""

    type: str
    seq: int = 0
    run_id: str = ""
    step_id: str = ""
    phase_id: str | None = None
    timestamp: datetime | None = None


class RunStarted(RunEvent):
    """Run 创建并开始执行。"""

    type: Literal["run_started"] = "run_started"
    status: RunStatus = RunStatus.RUNNING
    account_id: str = ""
    agent_id: str = ""
    skill_id: str | None = None
    user_goal: str = ""


class PhaseStarted(RunEvent):
    """进入阶段。"""

    type: Literal["phase_started"] = "phase_started"
    phase_name: str = ""
    attempt: int = 0
    iteration: int = 0


class LLMCallStarted(RunEvent):
    """一次 LLM 调用发起。"""

    type: Literal["llm_call_started"] = "llm_call_started"
    call_index: int = 0
    provider: str = ""
    model: str = ""


class LLMUsageUpdated(RunEvent):
    """LLM 调用用量更新。usage 键：input/output/total/cached_read/cached_write。"""

    type: Literal["llm_usage_updated"] = "llm_usage_updated"
    call_index: int = 0
    usage: dict[str, int] = Field(default_factory=dict)


class ActionProposed(RunEvent):
    """Action 被提议（LLM 建议，Engine 尚未验证）。"""

    type: Literal["action_proposed"] = "action_proposed"
    action_id: str = ""
    tool_name: str = ""
    args_summary: str = ""
    fingerprint: str = ""


class ActionRejected(RunEvent):
    """Action 被 Policy 拒绝（展示信息与内部 reason 分离）。"""

    type: Literal["action_rejected"] = "action_rejected"
    action_id: str = ""
    tool_name: str = ""
    reason_code: str = ""
    display_message: str = ""


class ToolCallStarted(RunEvent):
    """工具调用发起（进入 ToolBroker）。"""

    type: Literal["tool_call_started"] = "tool_call_started"
    action_id: str = ""
    call_id: str = ""
    tool_name: str = ""
    args_summary: str = ""


class ToolCallCompleted(RunEvent):
    """工具调用完成。"""

    type: Literal["tool_call_completed"] = "tool_call_completed"
    action_id: str = ""
    call_id: str = ""
    tool_name: str = ""
    ok: bool = True
    result_summary: str = ""
    duration_ms: int = 0
    truncated: bool = False


class ProgressUpdated(RunEvent):
    """进展更新（新增证据/产物/Contract 改善）。"""

    type: Literal["progress_updated"] = "progress_updated"
    progress_version: int = 0
    delta: int = 0
    new_evidence_count: int = 0
    new_artifact_count: int = 0


class ProgressStalled(RunEvent):
    """无进展预警（§12.4 命中时发出，可观测）。"""

    type: Literal["progress_stalled"] = "progress_stalled"
    consecutive_no_progress: int = 0


class ContractChecked(RunEvent):
    """Contract 校验结果。"""

    type: Literal["contract_checked"] = "contract_checked"
    contract_id: str = ""
    contract_type: ContractType
    verdict: ContractVerdict
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    score: float | None = None
    retryable: bool = False


class PhaseCompleted(RunEvent):
    """阶段完成（正常/降级/部分）。"""

    type: Literal["phase_completed"] = "phase_completed"
    status: PhaseStatus = PhaseStatus.COMPLETED
    outcome_type: PhaseExecutionOutcomeType | None = None
    limitations: list[str] = Field(default_factory=list)


class RunInputRequested(RunEvent):
    """需要用户补充输入（WAITING_INPUT 暂停事件，非结束事件，§17.2）。"""

    type: Literal["run_input_requested"] = "run_input_requested"
    question: str = ""
    missing_fields: list[str] = Field(default_factory=list)


class RunDegraded(RunEvent):
    """Run 降级（数据源/能力降级）。"""

    type: Literal["run_degraded"] = "run_degraded"
    degraded_sources: list[str] = Field(default_factory=list)
    reason: str = ""


class RunFinalizing(RunEvent):
    """进入 Finalize（任何终止路径都有明确可交付结果）。"""

    type: Literal["run_finalizing"] = "run_finalizing"
    reason: TerminationReason | None = None


class RunCompleted(RunEvent):
    """正常完成类终态事件（§17.1）：SUCCEEDED / PARTIAL，携带明确原因与未完成阶段。"""

    type: Literal["run_completed"] = "run_completed"
    status: Literal["succeeded", "partial"]
    termination_reason: TerminationReason
    final_output: str = ""
    completed_phases: list[str] = Field(default_factory=list)
    unfinished_phases: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    degraded_sources: list[str] = Field(default_factory=list)
    budget_snapshot: BudgetState | None = None


class RunCancelled(RunEvent):
    """取消终态事件（用户或系统取消，单独表达）。"""

    type: Literal["run_cancelled"] = "run_cancelled"
    termination_reason: TerminationReason = TerminationReason.USER_CANCELLED
    message: str = ""
    degraded_sources: list[str] = Field(default_factory=list)


class RunFailed(RunEvent):
    """失败终态事件（无可交付结果或不可恢复错误）。"""

    type: Literal["run_failed"] = "run_failed"
    termination_reason: TerminationReason = TerminationReason.INTERNAL_ERROR
    error_category: ErrorCategory | None = None
    message: str = ""
    recoverable: bool = False


class ThinkingStarted(RunEvent):
    """思考开始（展示分区开启，§17 高频展示事件）。"""

    type: Literal["thinking_started"] = "thinking_started"


class ThinkingDelta(RunEvent):
    """思考增量（打字机分区推送）。"""

    type: Literal["thinking_delta"] = "thinking_delta"
    text: str = ""


class ThinkingEnded(RunEvent):
    """思考结束（分区折叠，携带思考耗时）。"""

    type: Literal["thinking_ended"] = "thinking_ended"
    duration_ms: int = 0


class TextDelta(RunEvent):
    """正文增量（打字机推送）。"""

    type: Literal["text_delta"] = "text_delta"
    text: str = ""


class Heartbeat(RunEvent):
    """心跳（无数据期防代理超时）。"""

    type: Literal["heartbeat"] = "heartbeat"


RunEventUnion = Annotated[
    ActionProposed
    | ActionRejected
    | ContractChecked
    | Heartbeat
    | LLMCallStarted
    | LLMUsageUpdated
    | PhaseCompleted
    | PhaseStarted
    | ProgressStalled
    | ProgressUpdated
    | RunCancelled
    | RunCompleted
    | RunDegraded
    | RunFailed
    | RunFinalizing
    | RunInputRequested
    | RunStarted
    | TextDelta
    | ThinkingDelta
    | ThinkingEnded
    | ThinkingStarted
    | ToolCallCompleted
    | ToolCallStarted,
    Field(discriminator="type"),
]

run_event_adapter: TypeAdapter[RunEventUnion] = TypeAdapter(RunEventUnion)
