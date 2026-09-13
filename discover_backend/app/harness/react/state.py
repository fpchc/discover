"""Bounded ReAct 子图状态（§10）：节点间经 LangGraph 传递的内存态。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.environment.tools.models import ToolCallRequest, ToolResult
from app.harness.decision import AgentDecision
from app.harness.models import (
    ActionRecord,
    BudgetState,
    ObservationRecord,
    PhaseExecutionOutcome,
    PhaseExecutionRequest,
    ProgressState,
)
from app.llm.models import ChatMessage


class ReactGraphState(BaseModel):
    """Bounded ReAct 子图状态（§10）。普通内部节点不持久化，仅内存传递。"""

    request: PhaseExecutionRequest
    budget: BudgetState
    messages: list[ChatMessage] = Field(default_factory=list)
    pending_calls: list[ToolCallRequest] = Field(default_factory=list)
    decision: AgentDecision | None = None
    text_parts: str = ""
    action_records: list[ActionRecord] = Field(default_factory=list)
    observation_records: list[ObservationRecord] = Field(default_factory=list)
    last_results: list[ToolResult] = Field(default_factory=list)
    last_action_fingerprint: str = ""
    last_observation_fingerprint: str = ""
    new_evidence_count: int = 0
    new_artifact_count: int = 0
    progress: ProgressState = Field(default_factory=ProgressState)
    iteration: int = 0
    repair_attempts: int = 0
    degraded_sources: list[str] = Field(default_factory=list)
    terminate_reason: str = ""
    outcome: PhaseExecutionOutcome | None = None
