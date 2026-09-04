"""运行状态模型（react-runtime-v2-architecture §8）：Run/Phase/Budget/Progress/Termination。

单一动机：定义一次 Agent 执行（Run）的权威快照类型。所有跨生命周期边界传递的
状态一律 pydantic BaseModel，可序列化 / 反序列化；运行时句柄（客户端、文件路径等）
不写入本模块。平台不包含具体 Agent / Skill 字面量。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.runtime.contracts.models import ContractResult
from app.shared.errors.base import ErrorCategory


class RunStatus(StrEnum):
    """Run 生命周期状态（§7.1）。终态集合：SUCCEEDED / PARTIAL / FAILED / CANCELLED。"""

    CREATED = "created"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    RECOVERING = "recovering"
    CANCEL_REQUESTED = "cancel_requested"
    FINALIZING = "finalizing"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TerminationReason(StrEnum):
    """终止原因（§7.2）：终态与原因分离，PARTIAL 也必须有明确原因。"""

    COMPLETED = "completed"
    ITERATION_LIMIT = "iteration_limit"
    TOKEN_BUDGET = "token_budget"
    TIME_BUDGET = "time_budget"
    TOOL_BUDGET = "tool_budget"
    NO_PROGRESS = "no_progress"
    CONTRACT_FAILED = "contract_failed"
    REQUIRED_TOOL_UNAVAILABLE = "required_tool_unavailable"
    USER_CANCELLED = "user_cancelled"
    CLIENT_DISCONNECTED = "client_disconnected"
    RUNTIME_SHUTDOWN = "runtime_shutdown"
    INTERNAL_ERROR = "internal_error"


class PhaseStatus(StrEnum):
    """Phase 生命周期状态（§8.2）。"""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    PARTIAL = "partial"
    FAILED = "failed"


class ActionStatus(StrEnum):
    """Action 状态（§8.4）：从提议到执行完成或拒绝。"""

    PROPOSED = "proposed"
    ALLOWED = "allowed"
    REJECTED = "rejected"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ObservationStatus(StrEnum):
    """Observation 状态（§8.4）：工具结果分类。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EMPTY = "empty"
    DUPLICATE = "duplicate"
    DEGRADED = "degraded"


class BudgetKind(StrEnum):
    """预算维度（§8.3 / §13.1）：Token、时间、调用数、修复次数。"""

    ITERATIONS = "iterations"
    LLM_CALLS = "llm_calls"
    TOOL_CALLS = "tool_calls"
    TOTAL_TOKENS = "total_tokens"
    INPUT_TOKENS = "input_tokens"
    DURATION = "duration"
    REPAIR_ATTEMPTS = "repair_attempts"


class BudgetLimits(BaseModel):
    """预算上限（§8.3）：下层只能收紧，不能突破平台硬上限。"""

    max_iterations: int
    max_llm_calls: int
    max_tool_calls: int
    max_total_tokens: int
    max_input_tokens: int
    max_duration_seconds: float
    max_repair_attempts: int
    finalization_reserve_tokens: int


class BudgetUsage(BaseModel):
    """预算实际用量（§13.2 Finalization Reserve 工作/保留拆分）。"""

    iterations: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    duration_seconds: float = 0.0
    repair_attempts: int = 0
    finalization_tokens: int = 0


class BudgetState(BaseModel):
    """预算状态：限额 + 用量 + 软/硬超限标记（§10.2）。

    soft_exceeded 维度触发 → 停止工具探索进入部分总结；
    hard_exceeded 维度触发 → 确定性终止，禁止任何新 LLM/工具调用。
    """

    limits: BudgetLimits
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    soft_exceeded: list[BudgetKind] = Field(default_factory=list)
    hard_exceeded: list[BudgetKind] = Field(default_factory=list)


class ProgressState(BaseModel):
    """无进展判定状态（§8.5 / §12.4 六条件）。"""

    version: int = 0
    consecutive_no_progress: int = 0
    last_action_fingerprint: str | None = None
    last_observation_fingerprint: str | None = None
    new_evidence_count: int = 0
    new_artifact_count: int = 0
    contract_improved: bool = False


class CancellationState(BaseModel):
    """取消状态（§16.4 cancel flag）：用户取消与断连分离。"""

    requested: bool = False
    requested_at: datetime | None = None
    source: str = ""
    reason: str = ""


class ActionRecord(BaseModel):
    """Action 记录（§8.4）：一次工具决策，含规范化参数指纹。"""

    action_id: str
    step_id: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    arguments_fingerprint: str = ""
    status: ActionStatus = ActionStatus.PROPOSED
    retry_of: str | None = None
    idempotency_key: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int = 0


class ObservationRecord(BaseModel):
    """Observation 记录（§8.4）：工具结果，含观察指纹与进展增量。"""

    observation_id: str
    step_id: str
    action_id: str
    status: ObservationStatus
    content_summary: str = ""
    content_blob_ref: str | None = None
    observation_fingerprint: str = ""
    error_category: ErrorCategory | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    truncated: bool = False
    progress_delta: int = 0


class PhaseState(BaseModel):
    """阶段状态（§8.2）：独立记录 attempt / iteration / contract 结果。"""

    phase_id: str
    status: PhaseStatus = PhaseStatus.PENDING
    attempt: int = 0
    iteration: int = 0
    input: dict[str, object] = Field(default_factory=dict)
    output: dict[str, object] | None = None
    contract_results: list[ContractResult] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    degraded_sources: list[str] = Field(default_factory=list)
    repair_attempts: int = 0


class RunIdentity(BaseModel):
    """身份（§8.1）：run / conversation / message / account。"""

    run_id: str
    conversation_id: str
    message_id: str
    account_id: str


class RunGoal(BaseModel):
    """目标（§8.1）：agent / skill / 用户目标。"""

    agent_id: str
    skill_id: str | None = None
    user_goal: str = ""


class RunWorkflow(BaseModel):
    """Workflow 编排（§8.1）：阶段清单 + 当前阶段 + 阶段状态。"""

    phase_ids: list[str] = Field(default_factory=list)
    current_phase_id: str | None = None
    phases: dict[str, PhaseState] = Field(default_factory=dict)


class RunContext(BaseModel):
    """上下文（§8.1）：必要对话引用与阶段摘要。"""

    conversation_summary: str = ""
    phase_summaries: dict[str, str] = Field(default_factory=dict)


class RunOutput(BaseModel):
    """输出（§8.1）：阶段输出、最终草稿、产物引用。"""

    phase_outputs: dict[str, PhaseOutput] = Field(default_factory=dict)
    final_draft: str = ""
    artifact_ids: list[str] = Field(default_factory=list)


class RunControl(BaseModel):
    """控制（§8.1）：预算、进展、取消。"""

    budget: BudgetState
    progress: ProgressState = Field(default_factory=ProgressState)
    cancellation: CancellationState = Field(default_factory=CancellationState)


class RunAudit(BaseModel):
    """审计（§8.1）：当前 step、版本、创建/更新时间。"""

    current_step: int = 0
    version: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RunTermination(BaseModel):
    """终止（§8.1）：状态、原因、partial 标记、错误分类。"""

    status: RunStatus = RunStatus.CREATED
    reason: TerminationReason | None = None
    partial: bool = False
    error_category: ErrorCategory | None = None
    error_message: str = ""


class RunState(BaseModel):
    """Run 权威快照（§8.1 八节）。执行期内存权威，阶段/副作用边界持久化。"""

    identity: RunIdentity
    goal: RunGoal
    workflow: RunWorkflow
    context: RunContext = Field(default_factory=RunContext)
    output: RunOutput = Field(default_factory=RunOutput)
    control: RunControl
    audit: RunAudit = Field(default_factory=RunAudit)
    termination: RunTermination = Field(default_factory=RunTermination)


# ---- P0-2 接缝契约（§9.4）：PhaseExecutionRequest / Outcome / PhaseOutput ----


class PhaseExecutionRequest(BaseModel):
    """Workflow 调用 ReAct Executor 的输入（§9.4）。不把整个可变 RunState 交给 Executor。"""

    run_id: str
    phase_instance_id: str
    attempt: int = 0
    phase_goal: str = ""
    # 装配层产出的完整系统提示（AGENT.md + SKILL.md 正文 + 平台红线），ReAct
    # executor 优先使用，缺失时回落内置阶段提示（§18.4 LLM Context 组装）。
    system_prompt: str = ""
    phase_input: dict[str, object] = Field(default_factory=dict)
    upstream_outputs: dict[str, PhaseOutput] = Field(default_factory=dict)
    context_summary: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    budget: BudgetState
    contract_refs: list[str] = Field(default_factory=list)
    used_usage: BudgetUsage = Field(default_factory=BudgetUsage)
    recent_observations: list[ObservationRecord] = Field(default_factory=list)
    resume: bool = False


class PhaseExecutionOutcomeType(StrEnum):
    """Phase 执行结果分类（§9.4）。"""

    CANDIDATE_COMPLETED = "candidate_completed"
    FINAL_PROPOSED = "final_proposed"
    INPUT_REQUIRED = "input_required"
    PARTIAL_BUDGET = "partial_budget"
    PARTIAL_NO_PROGRESS = "partial_no_progress"
    FAILED = "failed"


class PhaseExecutionOutcome(BaseModel):
    """ReAct Executor 返回的结构化结果（§9.4）。"""

    outcome_type: PhaseExecutionOutcomeType
    candidate_output: dict[str, object] | None = None
    answer: str = ""
    usage_snapshot: BudgetUsage = Field(default_factory=BudgetUsage)
    budget_snapshot: BudgetState | None = None
    action_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reason_code: str = ""


class PhaseOutput(BaseModel):
    """通过 Contract 后的不可变、带版本阶段输出（§9.4）。下一阶段只读绑定。"""

    phase_id: str
    schema_version: int = 1
    data: dict[str, object] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    degraded_sources: list[str] = Field(default_factory=list)
    contract_results: list[ContractResult] = Field(default_factory=list)
    produced_at: datetime | None = None
