"""行动授权测试（P0 边界，W1）。

覆盖：superuser 旁路、审批矩阵（publish/delete 需审批）、read_only/write_file/
network 放行、fail-closed（接入 authorizer 但缺授权上下文）、未接入 authorizer 跳过。
"""

from __future__ import annotations

from app.config.settings import SideEffectType
from app.environment.tools.models import ToolCallRequest, ToolDescriptor, ToolResult, ToolSource
from app.harness.events.run_events import RunEvent
from app.harness.execution.pipeline import BrokerPort, ToolExecutionRequest, ToolRuntime
from app.harness.models import BudgetLimits, BudgetState, ProgressState
from app.harness.policy.authorization import (
    AuthorizationContext,
    AuthorizationDecisionType,
    PolicyAuthorizer,
)

_APPROVAL_REQUIRED = {SideEffectType.PUBLISH, SideEffectType.DELETE}


class _Broker(BrokerPort):
    """单工具目录桩：只含一个描述符，不真正执行。"""

    def __init__(self, descriptor: ToolDescriptor) -> None:
        self._descriptor = descriptor

    def get_descriptor(self, qualified_name: str) -> ToolDescriptor | None:
        return self._descriptor if self._descriptor.qualified_name == qualified_name else None

    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]:
        return []


class _Recorder:
    """事件记录器。"""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    async def emit(self, event: RunEvent) -> None:
        self.events.append(event)


def _descriptor(name: str, side_effect: SideEffectType) -> ToolDescriptor:
    return ToolDescriptor(
        qualified_name=name,
        short_name=name,
        namespace="test",
        description="工具",
        parameters={},
        source=ToolSource.META,
        tier=0,
        side_effect=side_effect,
    )


def _request(name: str, *, ctx: AuthorizationContext | None) -> ToolExecutionRequest:
    budget = BudgetState(
        limits=BudgetLimits(
            max_iterations=20,
            max_llm_calls=30,
            max_tool_calls=40,
            max_total_tokens=100000,
            max_input_tokens=80000,
            max_duration_seconds=300.0,
            max_repair_attempts=2,
            finalization_reserve_tokens=5000,
        )
    )
    return ToolExecutionRequest(
        run_id="run-1",
        phase_id="p1",
        iteration=0,
        calls=[ToolCallRequest(call_id="c1", tool_name=name, arguments={})],
        allowed_tools=[name],
        budget=budget,
        progress=ProgressState(),
        authorization=ctx,
    )


# ---- PolicyAuthorizer 判定 ----
def test_superuser_bypasses_approval_matrix() -> None:
    authorizer = PolicyAuthorizer(approval_required=_APPROVAL_REQUIRED)
    ctx = AuthorizationContext(account_id="a", superuser=True)
    decision = authorizer.authorize(ctx=ctx, side_effect=SideEffectType.DELETE, tool_name="t")
    assert decision.decision == AuthorizationDecisionType.ALLOW


def test_approval_required_side_effect_denied_for_normal_user() -> None:
    authorizer = PolicyAuthorizer(approval_required=_APPROVAL_REQUIRED)
    ctx = AuthorizationContext(account_id="a")
    decision = authorizer.authorize(ctx=ctx, side_effect=SideEffectType.PUBLISH, tool_name="t")
    assert decision.decision == AuthorizationDecisionType.DENY
    assert decision.reason_code == "approval_required"


def test_safe_side_effects_allowed() -> None:
    authorizer = PolicyAuthorizer(approval_required=_APPROVAL_REQUIRED)
    ctx = AuthorizationContext(account_id="a")
    for side_effect in (
        SideEffectType.READ_ONLY,
        SideEffectType.WRITE_FILE,
        SideEffectType.NETWORK,
    ):
        decision = authorizer.authorize(ctx=ctx, side_effect=side_effect, tool_name="t")
        assert decision.decision == AuthorizationDecisionType.ALLOW


# ---- ToolRuntime preflight 授权接入 ----
async def test_preflight_denies_approval_required_tool() -> None:
    broker = _Broker(_descriptor("t", SideEffectType.PUBLISH))
    authorizer = PolicyAuthorizer(approval_required=_APPROVAL_REQUIRED)
    runtime = ToolRuntime(broker=broker, emit=_Recorder().emit, authorizer=authorizer)
    result = await runtime.preflight(_request("t", ctx=AuthorizationContext(account_id="a")))
    assert result.pending == []
    assert result.rejections and result.rejections[0].message
    assert result.action_records[0].status == "rejected"


async def test_preflight_fails_closed_when_context_missing() -> None:
    broker = _Broker(_descriptor("t", SideEffectType.READ_ONLY))
    authorizer = PolicyAuthorizer(approval_required=_APPROVAL_REQUIRED)
    runtime = ToolRuntime(broker=broker, emit=_Recorder().emit, authorizer=authorizer)
    result = await runtime.preflight(_request("t", ctx=None))
    assert result.pending == []
    assert result.rejections and result.rejections[0].message


async def test_preflight_skips_authorization_when_no_authorizer() -> None:
    broker = _Broker(_descriptor("t", SideEffectType.PUBLISH))
    runtime = ToolRuntime(broker=broker, emit=_Recorder().emit)
    result = await runtime.preflight(_request("t", ctx=None))
    assert result.pending
