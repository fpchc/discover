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

from app.config.settings import SideEffectType
from app.environment.context.models import ArtifactRef
from app.environment.tools.models import ToolCallRequest, ToolDescriptor, ToolResult
from app.harness.events.run_events import (
    ActionProposed,
    RunEvent,
    ToolCallCompleted,
    ToolCallStarted,
)
from app.harness.models import (
    ActionRecord,
    ActionStatus,
    BudgetState,
    ObservationRecord,
    ObservationStatus,
    ProgressState,
)
from app.harness.policy.action import check_action
from app.harness.policy.authorization import (
    ActionAuthorizer,
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationDecisionType,
)
from app.harness.policy.models import PolicyDecisionType
from app.harness.progress import (
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

    run_id: str
    action_id: str
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    arguments_fingerprint: str = ""
    idempotency_key: str = ""
    side_effect_class: SideEffectClass = SideEffectClass.READ_ONLY
    planned_at: datetime | None = None


class CheckpointPort(Protocol):
    """副作用 Checkpoint 抽象：planned → executed/failed 状态机，None 时跳过。"""

    async def save_planned_action(self, planned: PlannedAction) -> None: ...
    async def mark_executed(self, run_id: str, action_id: str, *, ok: bool) -> None: ...
    async def load_pending(self, run_id: str) -> list[PlannedAction]: ...


class ArtifactRegistrar(Protocol):
    """产物登记抽象（组装层注入 FileService.register；None 时跳过）。"""

    async def register(
        self, *, source_path: Path, filename: str, created_by: str
    ) -> ArtifactRef: ...


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
    authorization: AuthorizationContext | None = None


class ToolExecutionResult(BaseModel):
    """管线输出：observations + artifacts + 更新后的 budget/progress。"""

    observations: list[ObservationRecord] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    action_records: list[ActionRecord] = Field(default_factory=list)
    results: list[ToolResult] = Field(default_factory=list)
    budget: BudgetState
    progress: ProgressState


class ToolRejection(BaseModel):
    """preflight 拒绝项：调用 + 面向模型的拒绝说明。"""

    call: ToolCallRequest
    message: str


class ToolPreflightResult(BaseModel):
    """preflight 输出：允许执行集合 + ActionRecord + 拒绝说明。"""

    pending: list[ToolCallRequest] = Field(default_factory=list)
    action_records: list[ActionRecord] = Field(default_factory=list)
    rejections: list[ToolRejection] = Field(default_factory=list)


class ToolRuntime:
    """Tool Runtime 管线（§15）。依赖经构造注入（DIP，CLAUDE.md §6）。"""

    def __init__(
        self,
        *,
        broker: BrokerPort,
        emit: Callable[[RunEvent], Awaitable[None]],
        checkpoint: CheckpointPort | None = None,
        artifacts: ArtifactRegistrar | None = None,
        authorizer: ActionAuthorizer | None = None,
        progress_threshold: int = 3,
        idempotency_prefix: str = "tool",
    ) -> None:
        self._broker = broker
        self._emit_fn = emit
        self._checkpoint = checkpoint
        self._artifacts = artifacts
        self._authorizer = authorizer
        self._progress_threshold = progress_threshold
        self._idempotency_prefix = idempotency_prefix

    async def preflight(self, request: ToolExecutionRequest) -> ToolPreflightResult:
        """Action 预检：descriptor 存在性 + 阶段白名单 + schema + 重复无进展。

        只判定不执行（Action Policy），返回允许执行集合、ActionRecord 与拒绝说明。
        """
        records: list[ActionRecord] = []
        pending: list[ToolCallRequest] = []
        rejections: list[ToolRejection] = []
        for call in request.calls:
            descriptor = self._broker.get_descriptor(call.tool_name)
            if descriptor is None:
                records.append(self._rejected(call))
                rejections.append(ToolRejection(call=call, message="请求的工具不在目录中"))
                continue
            fingerprint = action_fingerprint(
                call.tool_name, call.arguments, phase_id=request.phase_id
            )
            await self._emit_fn(
                ActionProposed(
                    run_id=request.run_id,
                    phase_id=request.phase_id,
                    tool_name=call.tool_name,
                    args_summary=str(call.arguments)[:200],
                    fingerprint=fingerprint,
                )
            )
            auth = self._authorize(request, descriptor, call)
            if auth.decision != AuthorizationDecisionType.ALLOW:
                records.append(
                    ActionRecord(
                        action_id=self._action_id(request, call),
                        step_id=f"{request.iteration}.{call.call_id}",
                        tool_name=call.tool_name,
                        arguments=dict(call.arguments),
                        arguments_fingerprint=fingerprint,
                        status=ActionStatus.REJECTED,
                    )
                )
                rejections.append(
                    ToolRejection(call=call, message=auth.display_message or "操作未获授权")
                )
                continue
            check = check_action(
                descriptor=descriptor,
                arguments=call.arguments,
                allowed_tools=request.allowed_tools,
                recent_actions=records,
                progress=request.progress,
                progress_threshold=self._progress_threshold,
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
            else:
                rejections.append(
                    ToolRejection(
                        call=call,
                        message=check.display_message or check.reason_code or "调用被拒绝",
                    )
                )
        return ToolPreflightResult(pending=pending, action_records=records, rejections=rejections)

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """执行一批工具调用：preflight + execute_prepared。"""
        preflight = await self.preflight(request)
        if not preflight.pending:
            return ToolExecutionResult(
                observations=[],
                artifacts=[],
                action_records=preflight.action_records,
                budget=request.budget,
                progress=request.progress,
            )
        return await self.execute_prepared(request, preflight.pending, preflight.action_records)

    async def execute_prepared(
        self,
        request: ToolExecutionRequest,
        pending: list[ToolCallRequest],
        records: list[ActionRecord],
    ) -> ToolExecutionResult:
        """执行已预检通过的调用：副作用预记录 → broker → normalize → 产物登记。"""
        # 副作用预记录必须先于任何外部执行：崩溃后恢复可据此判断是否已发生。
        planned_ids: set[str] = set()
        for call in pending:
            descriptor = self._broker.get_descriptor(call.tool_name)
            klass = (
                side_effect_class(descriptor.side_effect)
                if descriptor is not None
                else SideEffectClass.READ_ONLY
            )
            if klass != SideEffectClass.READ_ONLY:
                await self._save_planned(request, call, klass)
                planned_ids.add(self._action_id(request, call))
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
        artifacts: list[ArtifactRef] = []
        for call, result in zip(pending, results, strict=True):
            action_id = self._action_id(request, call)
            if action_id in planned_ids:
                await self._mark_executed(request, call, result)
            await self._emit_fn(
                ToolCallCompleted(
                    run_id=request.run_id,
                    phase_id=request.phase_id,
                    action_id=action_id,
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
            results=results,
            budget=request.budget,
            progress=request.progress,
        )

    def _action_id(self, request: ToolExecutionRequest, call: ToolCallRequest) -> str:
        return f"{request.phase_id}.{request.iteration}.{call.call_id}"

    def _authorize(
        self, request: ToolExecutionRequest, descriptor: ToolDescriptor, call: ToolCallRequest
    ) -> AuthorizationDecision:
        """行动授权判定：接入 Authorizer 却拿不到身份即 fail-closed（DENY）。"""
        if self._authorizer is None:
            return AuthorizationDecision(
                decision=AuthorizationDecisionType.ALLOW, reason_code="authorization_disabled"
            )
        if request.authorization is None:
            return AuthorizationDecision(
                decision=AuthorizationDecisionType.DENY,
                reason_code="missing_identity",
                display_message="缺少授权上下文，无法判定该操作权限",
            )
        return self._authorizer.authorize(
            ctx=request.authorization,
            side_effect=descriptor.side_effect,
            tool_name=call.tool_name,
        )

    @staticmethod
    def _rejected(call: ToolCallRequest) -> ActionRecord:
        return ActionRecord(
            action_id="",
            step_id="",
            tool_name=call.tool_name,
            arguments=dict(call.arguments),
            status=ActionStatus.REJECTED,
        )

    async def _save_planned(
        self, request: ToolExecutionRequest, call: ToolCallRequest, klass: SideEffectClass
    ) -> None:
        if self._checkpoint is None:
            return
        await self._checkpoint.save_planned_action(
            PlannedAction(
                run_id=request.run_id,
                action_id=self._action_id(request, call),
                tool_name=call.tool_name,
                arguments=dict(call.arguments),
                arguments_fingerprint=action_fingerprint(call.tool_name, call.arguments),
                idempotency_key=self._idempotency_key(call.tool_name, call.arguments),
                side_effect_class=klass,
                planned_at=datetime.now(),
            )
        )

    def _idempotency_key(self, tool_name: str, arguments: dict[str, object]) -> str:
        seed = repr(sorted(arguments.items(), key=lambda item: item[0]))
        return f"{self._idempotency_prefix}:{tool_name}:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"

    async def _mark_executed(
        self, request: ToolExecutionRequest, call: ToolCallRequest, result: ToolResult
    ) -> None:
        """副作用动作执行后落 executed/failed 状态（关 Checkpoint 状态机）。"""
        if self._checkpoint is None:
            return
        await self._checkpoint.mark_executed(
            request.run_id, self._action_id(request, call), ok=result.ok
        )

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
    ) -> ArtifactRef | None:
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
