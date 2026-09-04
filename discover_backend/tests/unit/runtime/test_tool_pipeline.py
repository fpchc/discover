"""Tool Runtime 管线测试（W4，§15）。

覆盖验收：副作用工具执行前 Checkpoint + 幂等键、产物与 Observation 关联、
preflight 拒绝（不存在/不在白名单）、MCP/Script 对上层透明（BrokerPort 抽象）。
"""

from __future__ import annotations

from pathlib import Path

from app.capabilities.tools.broker import ToolCallRequest, ToolResult
from app.capabilities.tools.descriptor import ToolDescriptor, ToolSource
from app.config.settings import SideEffectType
from app.interfaces.schemas.files import ArtifactRecord
from app.runtime.events.run_events import RunEvent, ToolCallCompleted, ToolCallStarted
from app.runtime.execution.pipeline import (
    BrokerPort,
    PlannedAction,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolRuntime,
    side_effect_class,
)
from app.runtime.models import BudgetLimits, BudgetState, ProgressState
from app.shared.errors.base import ErrorCategory


class _FakeBroker(BrokerPort):
    """脚本化 BrokerPort：目录 + 分发（记录调用，返回脚本结果）。"""

    def __init__(
        self,
        descriptors: dict[str, ToolDescriptor] | None = None,
        results: dict[str, ToolResult] | None = None,
    ) -> None:
        self._descriptors = descriptors or {}
        self._results = results or {}
        self.calls: list[list[ToolCallRequest]] = []

    def get_descriptor(self, qualified_name: str) -> ToolDescriptor | None:
        return self._descriptors.get(qualified_name)

    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]:
        self.calls.append(calls)
        return [self._results.get(call.tool_name, _ok(call, "默认结果")) for call in calls]


class _FakeCheckpoint:
    """记录 Planned Action 的 Checkpoint 桩。"""

    def __init__(self) -> None:
        self.planned: list[PlannedAction] = []

    async def save_planned_action(self, planned: PlannedAction) -> None:
        self.planned.append(planned)


class _FakeArtifacts:
    """产物登记桩：按请求生成 ArtifactRecord。"""

    async def register(
        self, *, source_path: Path, filename: str, created_by: str
    ) -> ArtifactRecord:
        del source_path, created_by
        return ArtifactRecord(
            artifact_id=f"art-{filename}", filename=filename, media_type="text/plain", size_bytes=1
        )


class _Recorder:
    """事件记录器。"""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    async def emit(self, event: RunEvent) -> None:
        self.events.append(event)


def _ok(call: ToolCallRequest, content: str) -> ToolResult:
    return ToolResult(call_id=call.call_id, tool_name=call.tool_name, ok=True, content=content)


def _descriptor(
    name: str, *, side_effect: SideEffectType = SideEffectType.READ_ONLY
) -> ToolDescriptor:
    return ToolDescriptor(
        qualified_name=name,
        short_name=name,
        namespace="test",
        description=f"工具 {name}",
        parameters={},
        source=ToolSource.META,
        tier=0,
        side_effect=side_effect,
    )


def _request(broker: _FakeBroker, workspace: Path | None = None) -> ToolExecutionRequest:
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
        calls=[
            ToolCallRequest(call_id="c1", tool_name="tool.a", arguments={"q": "x"}),
        ],
        allowed_tools=["tool.a"],
        budget=budget,
        progress=ProgressState(),
        workspace=workspace,
    )


async def _execute(
    *,
    broker: _FakeBroker,
    request: ToolExecutionRequest,
    checkpoint: _FakeCheckpoint | None = None,
    artifacts: _FakeArtifacts | None = None,
) -> tuple[ToolExecutionResult, _Recorder]:
    recorder = _Recorder()
    runtime = ToolRuntime(
        broker=broker,
        emit=recorder.emit,
        checkpoint=checkpoint,
        artifacts=artifacts,
    )
    result = await runtime.execute(request)
    return result, recorder


# ---- MCP/Script 透明：BrokerPort 抽象，上层不感知来源 ----
async def test_pipeline_executes_through_broker_abstraction() -> None:
    broker = _FakeBroker(
        descriptors={"tool.a": _descriptor("tool.a")},
        results={"tool.a": _ok(ToolCallRequest(call_id="c1", tool_name="tool.a"), "数据")},
    )
    result, recorder = await _execute(broker=broker, request=_request(broker))
    assert len(broker.calls) == 1
    assert result.observations[0].content_summary == "数据"
    assert any(isinstance(e, ToolCallStarted) for e in recorder.events)
    assert any(isinstance(e, ToolCallCompleted) for e in recorder.events)


# ---- preflight：不存在工具拒绝，不执行 ----
async def test_pipeline_rejects_missing_tool() -> None:
    broker = _FakeBroker()  # 无目录
    request = _request(broker)
    result, _recorder = await _execute(broker=broker, request=request)
    assert broker.calls == []
    assert result.observations == []
    assert result.action_records[0].status == "rejected"


# ---- preflight：不在白名单拒绝 ----
async def test_pipeline_rejects_tool_outside_whitelist() -> None:
    broker = _FakeBroker(descriptors={"tool.b": _descriptor("tool.b")})
    request = _request(broker)
    request.calls = [ToolCallRequest(call_id="c1", tool_name="tool.b", arguments={})]
    result, _recorder = await _execute(broker=broker, request=request)
    assert broker.calls == []
    assert result.action_records[0].status == "rejected"


# ---- 副作用：执行前 Checkpoint + 幂等键 ----
async def test_pipeline_checkpoints_side_effect_tool_with_idempotency_key() -> None:
    broker = _FakeBroker(
        descriptors={
            "tool.write": _descriptor("tool.write", side_effect=SideEffectType.WRITE_FILE)
        },
        results={
            "tool.write": _ok(ToolCallRequest(call_id="c1", tool_name="tool.write"), "写入成功")
        },
    )
    checkpoint = _FakeCheckpoint()
    request = _request(broker)
    request.calls = [
        ToolCallRequest(call_id="c1", tool_name="tool.write", arguments={"f": "a.txt"})
    ]
    request.allowed_tools = ["tool.write"]
    _result, _recorder = await _execute(broker=broker, request=request, checkpoint=checkpoint)
    assert len(checkpoint.planned) == 1
    planned = checkpoint.planned[0]
    assert planned.side_effect_class == "workspace_write"
    assert planned.idempotency_key
    assert planned.arguments_fingerprint


# ---- 副作用分类映射 ----
def test_side_effect_class_mapping() -> None:
    assert side_effect_class(SideEffectType.READ_ONLY) == "read_only"
    assert side_effect_class(SideEffectType.WRITE_FILE) == "workspace_write"
    assert side_effect_class(SideEffectType.DELETE) == "irreversible"
    assert side_effect_class(SideEffectType.NETWORK) == "external_write"
    assert side_effect_class(SideEffectType.PUBLISH) == "external_write"


# ---- 产物登记与 Observation 关联 ----
async def test_pipeline_registers_artifacts_linked_to_observation(tmp_path: Path) -> None:
    broker = _FakeBroker(
        descriptors={"tool.gen": _descriptor("tool.gen")},
        results={
            "tool.gen": _ok(
                ToolCallRequest(call_id="c1", tool_name="tool.gen"), "生成了文件"
            ).model_copy(update={"produced_files": ["out/report.txt"]})
        },
    )
    artifacts = _FakeArtifacts()
    request = _request(broker, workspace=tmp_path)
    request.calls = [ToolCallRequest(call_id="c1", tool_name="tool.gen", arguments={})]
    request.allowed_tools = ["tool.gen"]
    result, _recorder = await _execute(broker=broker, request=request, artifacts=artifacts)
    # 产物登记用 basename；Observation 保留完整相对路径做关联
    assert result.artifacts[0].artifact_id == "art-report.txt"
    assert result.observations[0].artifact_ids == ["out/report.txt"]


# ---- Observation 归一：失败分类 ----
async def test_pipeline_normalizes_failure_observation() -> None:
    failed = ToolResult(
        call_id="c1",
        tool_name="tool.a",
        ok=False,
        error_category=ErrorCategory.SERVER,
        message="上游挂了",
        suggestion="稍后重试",
    )
    broker = _FakeBroker(descriptors={"tool.a": _descriptor("tool.a")}, results={"tool.a": failed})
    result, _recorder = await _execute(broker=broker, request=_request(broker))
    assert result.observations[0].status == "failed"
    assert result.observations[0].error_category == ErrorCategory.SERVER
