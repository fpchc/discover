"""Tool Runtime 管线（react-runtime-v2-architecture §15）。

单一动机：把工具执行做成完整确定性管线——resolve descriptor → schema 验证 →
阶段授权 → 重复/无进展检查 → 副作用分类 → 幂等键 → broker → normalize →
产物登记 → progress 评估 → checkpoint → 事件。MCP/Script 对上层透明（§15）。

迁移策略：旧 ``execution/executor.py``（ToolExecutor）仍被旧 Runtime 使用，
本模块为 管线，W8 统一清理旧代码（§22 短期共存）。Checkpoint 持久化实现在
W6-W7 接入；本层通过 ``CheckpointPort`` 抽象（None 时跳过，测试无需落库）。
依赖全部注入（DIP，CLAUDE.md §6），无模块级全局可变状态（§13.2）。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from app.capabilities.tools.broker import ToolCallRequest, ToolResult
from app.capabilities.tools.descriptor import ToolDescriptor
from app.config.settings import SideEffectType
from app.interfaces.schemas.files import ArtifactRecord
from app.runtime.events.run_events import (
    ActionProposed,
    RunEvent,
    ToolCallCompleted,
    ToolCallStarted,
)
from app.runtime.models import (
    ActionRecord,
    ActionStatus,
    BudgetState,
    ObservationRecord,
    ObservationStatus,
    ProgressState,
)
from app.runtime.policy.action import check_action
from app.runtime.policy.models import PolicyDecisionType
from app.runtime.react.progress import (
    action_fingerprint,
    observation_fingerprint,
)


class SideEffectClass(StrEnum):
    """副作用分类（§15.2）：决定是否执行前 Checkpoint 与幂等策略。"""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE = "external_write"
    IRREVERSIBLE = "irreversible"


class BrokerPort(Protocol):
    """工具目录 + 分发抽象（ToolBroker 实现，唯一出口，DIP §6）。"""

    def get_descriptor(self, qualified_name: str) -> ToolDescriptor | None: ...
    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]: ...


def side_effect_class(side_effect: SideEffectType) -> SideEffectClass:
    """SideEffectType → 副作用分类映射。READ_ONLY 无需 Checkpoint。"""
    if side_effect == SideEffectType.READ_ONLY:
        return SideEffectClass.READ_ONLY
    if side_effect == SideEffectType.WRITE_FILE:
        return SideEffectClass.WORKSPACE_WRITE
    if side_effect == SideEffectType.DELETE:
        return SideEffectClass.IRREVERSIBLE
    return SideEffectClass.EXTERNAL_WRITE


class PlannedAction(BaseModel):
    """副作用工具执行前保存的检查点（§15.2 / §16.2-5）：幂等键 + 参数指纹。"""

    action_id: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    arguments_fingerprint: str = ""
    idempotency_key: str = ""
    side_effect_class: SideEffectClass = SideEffectClass.READ_ONLY
    planned_at: datetime | None = None


class CheckpointPort(Protocol):
    """副作用 Checkpoint 抽象（W6-W7 接持久化 store；None 时跳过）。"""

    async def save_planned_action(self, planned: PlannedAction) -> None: ...


class ArtifactRegistrar(Protocol):
    """产物登记抽象（组装层注入 FileService.register；None 时跳过）。"""

    async def register(
        self, *, source_path: Path, filename: str, created_by: str
    ) -> ArtifactRecord: ...


class ToolExecutionRequest(BaseModel):
    """管线输入：一次工具批次执行的完整上下文。"""

    run_id: str
    phase_id: str
    iteration: int
    calls: list[ToolCallRequest]
    allowed_tools: list[str]
    budget: BudgetState
    progress: ProgressState
    account_id: str = ""
    workspace: Path | None = None
    created_by: str = "agent"


class ToolExecutionResult(BaseModel):
    """管线输出：observations + artifacts + 更新后的 budget/progress。"""

    observations: list[ObservationRecord] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    action_records: list[ActionRecord] = Field(default_factory=list)
    budget: BudgetState
    progress: ProgressState


class ToolRuntime:
    """Tool Runtime 管线（§15）。依赖经构造注入（DIP，CLAUDE.md §6）。"""

    def __init__(
        self,
        *,
        broker: BrokerPort,
        emit: Callable[[RunEvent], Awaitable[None]],
        checkpoint: CheckpointPort | None = None,
        artifacts: ArtifactRegistrar | None = None,
        progress_threshold: int = 3,
        idempotency_prefix: str = "tool",
    ) -> None:
        self._broker = broker
        self._emit_fn = emit
        self._checkpoint = checkpoint
        self._artifacts = artifacts
        self._progress_threshold = progress_threshold
        self._idempotency_prefix = idempotency_prefix

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """执行一批工具调用，返回归一后的观察与状态更新。"""
        records: list[ActionRecord] = []
        pending: list[ToolCallRequest] = []
        for call in request.calls:
            descriptor = self._broker.get_descriptor(call.tool_name)
            if descriptor is None:
                records.append(self._rejected(call))
                continue
            await self._emit_fn(
                ActionProposed(
                    run_id=request.run_id,
                    phase_id=request.phase_id,
                    tool_name=call.tool_name,
                    args_summary=str(call.arguments)[:200],
                    fingerprint=action_fingerprint(
                        call.tool_name, call.arguments, phase_id=request.phase_id
                    ),
                )
            )
            check = check_action(
                descriptor=descriptor,
                arguments=call.arguments,
                allowed_tools=request.allowed_tools,
                recent_actions=records,
                progress=request.progress,
                progress_threshold=self._progress_threshold,
            )
            fingerprint = action_fingerprint(
                call.tool_name, call.arguments, phase_id=request.phase_id
            )
            allowed = check.decision == PolicyDecisionType.ALLOW
            records.append(
                ActionRecord(
                    action_id=self._action_id(request, call),
                    step_id=f"{request.iteration}.{call.call_id}",
                    tool_name=call.tool_name,
                    arguments=dict(call.arguments),
                    arguments_fingerprint=fingerprint,
                    status=ActionStatus.ALLOWED if allowed else ActionStatus.REJECTED,
                )
            )
            if allowed:
                pending.append(call)
        if not pending:
            return ToolExecutionResult(
                observations=[],
                artifacts=[],
                action_records=records,
                budget=request.budget,
                progress=request.progress,
            )
        for call in pending:
            await self._emit_fn(
                ToolCallStarted(
                    run_id=request.run_id,
                    phase_id=request.phase_id,
                    action_id=self._action_id(request, call),
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    args_summary=str(call.arguments)[:200],
                )
            )
        results = await self._broker.execute(pending)
        observations: list[ObservationRecord] = []
        artifacts: list[ArtifactRecord] = []
        for call, result in zip(pending, results, strict=True):
            descriptor = self._broker.get_descriptor(call.tool_name)
            klass = (
                side_effect_class(descriptor.side_effect)
                if descriptor is not None
                else SideEffectClass.READ_ONLY
            )
            if klass != SideEffectClass.READ_ONLY:
                await self._save_planned(call, klass)
            await self._emit_fn(
                ToolCallCompleted(
                    run_id=request.run_id,
                    phase_id=request.phase_id,
                    action_id=self._action_id(request, call),
                    call_id=result.call_id,
                    tool_name=result.tool_name,
                    ok=result.ok,
                    result_summary=(result.content or result.message)[:300],
                    duration_ms=result.duration_ms,
                    truncated=result.truncated,
                )
            )
            observations.append(self._normalize(request, call, result))
            for rel in result.produced_files:
                artifact = await self._register_artifact(request, rel)
                if artifact is not None:
                    artifacts.append(artifact)
        return ToolExecutionResult(
            observations=observations,
            artifacts=artifacts,
            action_records=records,
            budget=request.budget,
            progress=request.progress,
        )

    def _action_id(self, request: ToolExecutionRequest, call: ToolCallRequest) -> str:
        return f"{request.phase_id}.{request.iteration}.{call.call_id}"

    @staticmethod
    def _rejected(call: ToolCallRequest) -> ActionRecord:
        return ActionRecord(
            action_id="",
            step_id="",
            tool_name=call.tool_name,
            arguments=dict(call.arguments),
            status=ActionStatus.REJECTED,
        )

    async def _save_planned(self, call: ToolCallRequest, klass: SideEffectClass) -> None:
        if self._checkpoint is None:
            return
        await self._checkpoint.save_planned_action(
            PlannedAction(
                action_id=call.call_id,
                tool_name=call.tool_name,
                arguments=dict(call.arguments),
                arguments_fingerprint=action_fingerprint(call.tool_name, call.arguments),
                idempotency_key=self._idempotency_key(call.tool_name, call.arguments),
                side_effect_class=klass,
            )
        )

    def _idempotency_key(self, tool_name: str, arguments: dict[str, object]) -> str:
        seed = repr(sorted(arguments.items(), key=lambda item: item[0]))
        return f"{self._idempotency_prefix}:{tool_name}:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"

    def _normalize(
        self, request: ToolExecutionRequest, call: ToolCallRequest, result: ToolResult
    ) -> ObservationRecord:
        return ObservationRecord(
            observation_id=self._action_id(request, call),
            step_id=f"{request.iteration}.{call.call_id}",
            action_id=call.call_id,
            status=_result_status(result),
            content_summary=(result.content or "")[:500],
            observation_fingerprint=observation_fingerprint(
                ok=result.ok,
                content_summary=result.content,
                error_category=result.error_category,
                artifact_summary=",".join(result.produced_files),
            ),
            error_category=result.error_category,
            artifact_ids=list(result.produced_files),
            truncated=result.truncated,
            progress_delta=1 if result.ok and result.content else 0,
        )

    async def _register_artifact(
        self, request: ToolExecutionRequest, rel: str
    ) -> ArtifactRecord | None:
        if self._artifacts is None or request.workspace is None:
            return None
        try:
            return await self._artifacts.register(
                source_path=request.workspace / rel,
                filename=Path(rel).name,
                created_by=request.created_by,
            )
        except Exception:
            return None


def _result_status(result: ToolResult) -> ObservationStatus:
    if result.ok:
        return ObservationStatus.SUCCEEDED if result.content else ObservationStatus.EMPTY
    return ObservationStatus.FAILED
