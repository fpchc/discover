"""runtime/execution ToolExecutor 单测：Action → Observation 聚合（事件/门禁/产物）。

ToolExecutor 把 engine.tool_node 的「分发 + 事件 + 门禁 + 产物登记」抽为独立执行器；
本测试用 broker/files/emitter 桩验证回写逻辑（无 DB、无真实工具）。
"""

from pathlib import Path

from app.capabilities.llm.models import ChatMessage
from app.capabilities.tools.broker import ToolCallRequest, ToolResult
from app.interfaces.schemas.files import ArtifactRecord
from app.runtime.events.events import (
    ArtifactReadyEvent,
    GateCheckedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from app.runtime.execution.executor import ToolExecutor
from app.shared.errors.base import ErrorCategory


class _StubBroker:
    """只响应 execute 的工具代理桩（不激活技能）。"""

    def __init__(self, results: list[ToolResult]) -> None:
        self.results = results
        self.received: list[list[ToolCallRequest]] = []

    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]:
        self.received.append(calls)
        return self.results


class _StubFiles:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, str]] = []

    async def register(
        self, *, created_by: str, source_path: Path, filename: str
    ) -> ArtifactRecord:
        self.calls.append((created_by, source_path, filename))
        return ArtifactRecord(
            artifact_id="art-1", filename=filename, media_type="text/plain", size_bytes=42
        )


class _RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit(self, event: object) -> None:
        self.events.append(event)


def _result(call_id: str, *, ok: bool = True, produced: list[str] | None = None) -> ToolResult:
    return ToolResult(
        call_id=call_id,
        tool_name="finder.research.script.run",
        ok=ok,
        content="ok" if ok else "",
        message="" if ok else "执行失败",
        error_category=None if ok else ErrorCategory.SCRIPT,
        produced_files=produced or [],
    )


def _execute(
    executor: ToolExecutor,
    calls: list[ToolCallRequest],
    *,
    emitter: _RecordingEmitter,
    files: _StubFiles,
) -> object:
    return executor.execute(
        calls,
        emitter=emitter,  # type: ignore[arg-type]
        account_id="acct-1",
        workspace=Path("/ws"),
        turn=3,
    )


async def test_execute_emits_started_completed_and_builds_messages() -> None:
    broker = _StubBroker([_result("c1")])
    files = _StubFiles()
    emitter = _RecordingEmitter()
    executor = ToolExecutor(broker, files)  # type: ignore[arg-type]
    outcome = await _execute(
        executor,
        [
            ToolCallRequest(
                call_id="c1", tool_name="finder.research.script.run", arguments={"q": "x"}
            )
        ],
        emitter=emitter,
        files=files,
    )
    assert isinstance(emitter.events[0], ToolCallStartedEvent)
    assert isinstance(emitter.events[1], ToolCallCompletedEvent)
    assert outcome.messages == [ChatMessage(role="tool", content="ok", tool_call_id="c1")]
    assert outcome.gate_status == {}
    assert outcome.artifacts == []
    assert broker.received == [
        [
            ToolCallRequest(
                call_id="c1", tool_name="finder.research.script.run", arguments={"q": "x"}
            )
        ]
    ]


async def test_execute_aggregates_gates_and_artifacts() -> None:
    gate_ok = ToolResult(
        call_id="g1", tool_name="finder.research.script.gate_render_pass", ok=True, content="通过"
    )
    gate_fail = ToolResult(
        call_id="g2",
        tool_name="finder.research.script.gate_render_pass",
        ok=False,
        content="",
        message="报告缺字段",
    )
    producer = _result("p1", produced=["output/report.json"])
    broker = _StubBroker([gate_ok, gate_fail, producer])
    files = _StubFiles()
    emitter = _RecordingEmitter()
    executor = ToolExecutor(broker, files)  # type: ignore[arg-type]
    calls = [
        ToolCallRequest(
            call_id="g1", tool_name="finder.research.script.gate_render_pass", arguments={}
        ),
        ToolCallRequest(
            call_id="g2", tool_name="finder.research.script.gate_render_pass", arguments={}
        ),
        ToolCallRequest(call_id="p1", tool_name="finder.research.script.run", arguments={}),
    ]
    outcome = await _execute(executor, calls, emitter=emitter, files=files)
    assert outcome.gate_status["render_pass"].passed is False
    assert outcome.gate_status["render_pass"].failures == ["报告缺字段"]
    assert outcome.gate_status["render_pass"].turn == 3
    assert [a.filename for a in outcome.artifacts] == ["report.json"]
    assert files.calls == [("acct-1", Path("/ws/output/report.json"), "report.json")]
    assert any(isinstance(e, GateCheckedEvent) for e in emitter.events)
    assert any(isinstance(e, ArtifactReadyEvent) for e in emitter.events)


async def test_execute_failed_result_message_in_tool_message() -> None:
    broker = _StubBroker([_result("c1", ok=False)])
    files = _StubFiles()
    emitter = _RecordingEmitter()
    executor = ToolExecutor(broker, files)  # type: ignore[arg-type]
    outcome = await _execute(
        executor,
        [ToolCallRequest(call_id="c1", tool_name="finder.research.script.run", arguments={})],
        emitter=emitter,
        files=files,
    )
    assert outcome.messages == [ChatMessage(role="tool", content="执行失败", tool_call_id="c1")]
