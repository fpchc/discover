"""P0-1 parse_decision 五条归一规则测试（W2）。"""

from __future__ import annotations

from app.capabilities.llm.stream_parser import ToolCall
from app.runtime.react.decision import (
    AgentDecisionType,
    parse_decision,
)


def _call(name: str, *, arguments: str = "{}", call_id: str = "c1") -> ToolCall:
    return ToolCall(index=0, id=call_id, name=name, arguments=arguments)


# ---- 规则①：仅普通工具 → CALL_TOOLS ----
def test_regular_tools_yield_call_tools() -> None:
    calls = [_call("tool.a", arguments='{"q": "x"}'), _call("tool.b")]
    decision = parse_decision(calls)
    assert decision.decision_type == AgentDecisionType.CALL_TOOLS
    assert len(decision.tool_calls) == 2
    assert decision.tool_calls[0].tool_name == "tool.a"
    assert decision.tool_calls[0].arguments == {"q": "x"}


# ---- 规则②：恰好一个控制工具 → 对应控制决策 ----
def test_complete_phase_control() -> None:
    decision = parse_decision(
        [_call("complete_phase", arguments='{"summary": "完成", "evidence_refs": ["e1"]}')]
    )
    assert decision.decision_type == AgentDecisionType.COMPLETE_PHASE
    assert decision.complete_phase is not None
    assert decision.complete_phase.summary == "完成"


def test_final_answer_control() -> None:
    decision = parse_decision([_call("submit_final_answer", arguments='{"answer": "结论"}')])
    assert decision.decision_type == AgentDecisionType.FINAL_ANSWER
    assert decision.final_answer is not None
    assert decision.final_answer.answer == "结论"


def test_clarification_control() -> None:
    decision = parse_decision(
        [_call("request_clarification", arguments='{"question": "缺什么？"}')]
    )
    assert decision.decision_type == AgentDecisionType.NEED_CLARIFICATION
    assert decision.clarification is not None
    assert decision.clarification.question == "缺什么？"


# ---- 规则③：控制 + 普通混用 → INVALID ----
def test_mixed_control_and_regular_invalid() -> None:
    decision = parse_decision([_call("tool.a"), _call("complete_phase")])
    assert decision.decision_type == AgentDecisionType.INVALID_DECISION
    assert decision.invalid_reason == "control_tools_mixed_with_regular_tools"


# ---- 规则④：多个控制工具 → INVALID ----
def test_multiple_control_tools_invalid() -> None:
    decision = parse_decision([_call("complete_phase"), _call("submit_final_answer")])
    assert decision.decision_type == AgentDecisionType.INVALID_DECISION
    assert decision.invalid_reason == "multiple_control_tools"


# ---- 规则⑤：无工具调用 ----
def test_no_tool_calls_text_only() -> None:
    decision = parse_decision([], text_only=True)
    assert decision.decision_type == AgentDecisionType.INVALID_DECISION
    assert decision.invalid_reason == "text_only_no_tool_call"


def test_no_tool_calls_empty() -> None:
    decision = parse_decision([])
    assert decision.decision_type == AgentDecisionType.INVALID_DECISION
    assert decision.invalid_reason == "empty_decision"


# ---- 参数解析失败 / 未知控制工具 ----
def test_invalid_control_args() -> None:
    decision = parse_decision([_call("complete_phase", arguments="not json")])
    assert decision.decision_type == AgentDecisionType.INVALID_DECISION
    assert decision.invalid_reason == "invalid_control_tool_args:complete_phase"


def test_unknown_tool_is_regular_path() -> None:
    """非保留名的工具走普通工具路径（CALL_TOOLS），存在性由 Action Policy 校验。"""
    decision = parse_decision([_call("unknown_tool")])
    assert decision.decision_type == AgentDecisionType.CALL_TOOLS
    assert decision.tool_calls[0].tool_name == "unknown_tool"
