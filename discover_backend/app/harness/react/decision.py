"""结构化决策模型（react-runtime-v2-architecture §10.1，P0-1）。

单一动机：把 LLM 流归一为确定性 AgentDecision，供 parse_decision 节点消费。
三个保留控制工具（complete_phase / submit_final_answer / request_clarification）
属于 Runtime 保留命名空间，Skill/MCP/脚本不得注册同名工具；它们不进 ToolBroker，
不产生 ToolCallStarted/Completed 事件。
"""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError

from app.capabilities.llm.models import ChatToolSpec, ToolFunction
from app.capabilities.llm.stream_parser import ToolCall
from app.capabilities.tools.broker import ToolCallRequest


class ControlToolName(StrEnum):
    """平台保留控制工具名称（§10.1 保留命名空间）。"""

    COMPLETE_PHASE = "complete_phase"
    SUBMIT_FINAL_ANSWER = "submit_final_answer"
    REQUEST_CLARIFICATION = "request_clarification"


class AgentDecisionType(StrEnum):
    """归一后的决策类型（§10.1 映射规则）。"""

    CALL_TOOLS = "call_tools"
    COMPLETE_PHASE = "complete_phase"
    FINAL_ANSWER = "final_answer"
    NEED_CLARIFICATION = "need_clarification"
    INVALID_DECISION = "invalid_decision"


class CompletePhaseParams(BaseModel):
    """complete_phase 参数：candidate output + 摘要 + 证据引用。"""

    output: dict[str, object] = Field(default_factory=dict)
    summary: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FinalAnswerParams(BaseModel):
    """submit_final_answer 参数：最终答案。"""

    answer: str = ""
    structured_output: dict[str, object] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ClarificationParams(BaseModel):
    """request_clarification 参数：缺失输入说明。"""

    question: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    reason: str = ""


class AgentDecision(BaseModel):
    """parse_decision 的确定性输出（§10.1 五类映射结果）。"""

    decision_type: AgentDecisionType
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    complete_phase: CompletePhaseParams | None = None
    final_answer: FinalAnswerParams | None = None
    clarification: ClarificationParams | None = None
    invalid_reason: str = ""

    @staticmethod
    def from_tool_calls(calls: list[ToolCallRequest]) -> AgentDecision:
        """规则①：仅普通工具调用 → CALL_TOOLS，允许同批多个。"""
        return AgentDecision(decision_type=AgentDecisionType.CALL_TOOLS, tool_calls=calls)


_CONTROL_TOOL_NAMES: frozenset[str] = frozenset(tool.value for tool in ControlToolName)

_CONTROL_TOOL_PARAMS: tuple[tuple[str, str, type[BaseModel]], ...] = (
    (
        ControlToolName.COMPLETE_PHASE.value,
        "提议当前阶段完成，附候选输出与摘要",
        CompletePhaseParams,
    ),
    (
        ControlToolName.SUBMIT_FINAL_ANSWER.value,
        "提交最终答案",
        FinalAnswerParams,
    ),
    (
        ControlToolName.REQUEST_CLARIFICATION.value,
        "请求用户补充缺失输入",
        ClarificationParams,
    ),
)


def control_tool_specs() -> list[ChatToolSpec]:
    """三个保留控制工具的 ChatToolSpec（§10.1 注入 ChatRequest.tools）。

    参数 schema 由 Runtime 从 Pydantic 模型生成；控制工具不进入 ToolBroker，
    不产生 ToolCallStarted/Completed 事件。
    """
    specs: list[ChatToolSpec] = []
    for name, description, params_model in _CONTROL_TOOL_PARAMS:
        schema = params_model.model_json_schema()
        specs.append(
            ChatToolSpec(
                function=ToolFunction(
                    name=name,
                    description=description,
                    parameters=schema,
                )
            )
        )
    return specs


def _parse_args(raw: str) -> dict[str, object]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _to_request(call: ToolCall) -> ToolCallRequest:
    return ToolCallRequest(
        call_id=call.id or "",
        tool_name=call.name or "",
        arguments=_parse_args(call.arguments),
    )


def _invalid(reason: str) -> AgentDecision:
    return AgentDecision(decision_type=AgentDecisionType.INVALID_DECISION, invalid_reason=reason)


def _control_decision(call: ToolCall) -> AgentDecision:
    """规则②：恰好一个控制工具 → 映射为对应控制决策（§10.1 映射表）。

    控制工具参数必须为合法 JSON dict；解析失败 / schema 校验失败均判 INVALID，
    计入 LLM / Token / repair budget（§10.1 决策验证）。
    """
    name = call.name or ""
    try:
        data = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return _invalid(f"invalid_control_tool_args:{name}")
    if not isinstance(data, dict):
        return _invalid(f"invalid_control_tool_args:{name}")
    try:
        if name == ControlToolName.COMPLETE_PHASE.value:
            return AgentDecision(
                decision_type=AgentDecisionType.COMPLETE_PHASE,
                complete_phase=CompletePhaseParams.model_validate(data),
            )
        if name == ControlToolName.SUBMIT_FINAL_ANSWER.value:
            return AgentDecision(
                decision_type=AgentDecisionType.FINAL_ANSWER,
                final_answer=FinalAnswerParams.model_validate(data),
            )
        if name == ControlToolName.REQUEST_CLARIFICATION.value:
            return AgentDecision(
                decision_type=AgentDecisionType.NEED_CLARIFICATION,
                clarification=ClarificationParams.model_validate(data),
            )
    except ValidationError:
        return _invalid(f"invalid_control_tool_args:{name}")
    return _invalid(f"unknown_control_tool:{name}")


def parse_decision(tool_calls: list[ToolCall], *, text_only: bool = False) -> AgentDecision:
    """ToolCallsChunk 归一为 AgentDecision（§10.1 五条确定性规则）。

    规则①：仅普通工具 → CALL_TOOLS；
    规则②：恰好一个控制工具 → 对应控制决策；
    规则③：控制 + 普通混用 → INVALID_DECISION；
    规则④：多个控制工具 → INVALID_DECISION；
    规则⑤：无工具调用 → text_only 判定（专家 Workflow 中为非权威 draft）。

    解析失败与格式修复计入 LLM / Token / repair budget（§10.1 决策验证）。
    """
    if not tool_calls:
        return _invalid("text_only_no_tool_call" if text_only else "empty_decision")
    control_calls = [call for call in tool_calls if (call.name or "") in _CONTROL_TOOL_NAMES]
    regular_calls = [call for call in tool_calls if (call.name or "") not in _CONTROL_TOOL_NAMES]
    if control_calls and regular_calls:
        return _invalid("control_tools_mixed_with_regular_tools")
    if len(control_calls) > 1:
        return _invalid("multiple_control_tools")
    if control_calls:
        return _control_decision(control_calls[0])
    return AgentDecision.from_tool_calls([_to_request(call) for call in regular_calls])
