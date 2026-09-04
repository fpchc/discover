"""P0-1 结构化决策模型测试（W1）：控制工具命名空间、五类决策、归一规则。"""

from __future__ import annotations

from app.capabilities.tools.broker import ToolCallRequest
from app.runtime.react.decision import (
    AgentDecision,
    AgentDecisionType,
    ControlToolName,
)


def test_control_tool_names_are_reserved() -> None:
    assert {
        ControlToolName.COMPLETE_PHASE.value,
        ControlToolName.SUBMIT_FINAL_ANSWER.value,
        ControlToolName.REQUEST_CLARIFICATION.value,
    } == {"complete_phase", "submit_final_answer", "request_clarification"}


def test_from_tool_calls_yields_call_tools() -> None:
    calls = [
        ToolCallRequest(call_id="c1", tool_name="tool.a", arguments={"q": "x"}),
        ToolCallRequest(call_id="c2", tool_name="tool.b", arguments={}),
    ]
    decision = AgentDecision.from_tool_calls(calls)
    assert decision.decision_type == AgentDecisionType.CALL_TOOLS
    assert len(decision.tool_calls) == 2


def test_decision_round_trip() -> None:
    decision = AgentDecision(
        decision_type=AgentDecisionType.COMPLETE_PHASE,
        complete_phase={"output": {"score": 1}, "summary": "完成"},
    )
    restored = AgentDecision.model_validate_json(decision.model_dump_json())
    assert restored.decision_type == AgentDecisionType.COMPLETE_PHASE
    assert restored.complete_phase is not None
    assert restored.complete_phase.summary == "完成"


def test_decision_defaults_invalid_reason() -> None:
    decision = AgentDecision(decision_type=AgentDecisionType.INVALID_DECISION)
    assert decision.invalid_reason == ""
    assert decision.tool_calls == []
