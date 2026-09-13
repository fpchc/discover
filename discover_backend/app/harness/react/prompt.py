"""Bounded ReAct 的提示词与结果/判定辅助（纯函数）。"""

from __future__ import annotations

import json

from app.environment.tools.models import ToolCallRequest, ToolResult
from app.harness.models import ObservationStatus, PhaseExecutionRequest
from app.harness.policy.models import PolicyDecision, PolicyDecisionType
from app.harness.react.state import ReactGraphState
from app.llm.chunks import ToolCall
from app.llm.models import ChatMessage, ChatToolCall, ChatToolCallFunction
from app.shared.utils.sanitize import truncate


def _to_chat_tool_call(call: ToolCall) -> ChatToolCall:
    return ChatToolCall(
        id=call.id or "",
        function=ChatToolCallFunction(name=call.name or "", arguments=call.arguments),
    )


def _parse_call_args(call: ToolCall) -> dict[str, object]:
    try:
        data = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _to_stream_call(call: ToolCallRequest) -> ToolCall:
    return ToolCall(
        index=0,
        id=call.call_id,
        name=call.tool_name,
        arguments=json.dumps(call.arguments, ensure_ascii=False),
    )


def _repair_hint(reason: str) -> str:
    """INVALID 决策 → 面向模型的定向修复指令（§10.1 格式修复）。"""
    if "text_only" in reason or "empty_decision" in reason:
        return (
            "请调用 submit_final_answer 提交最终答案，answer 字段放完整信息卡正文；"
            "不要只输出文本或只思考。"
        )
    if "control_tool" in reason:
        return "submit_final_answer 参数必须为合法 JSON，且 answer 必须包含完整信息卡正文。"
    return "上一轮工具决策格式非法，请重新输出符合要求的工具调用。"


def _repair_messages(state: ReactGraphState, reason: str) -> list[ChatMessage]:
    """格式修复反馈：注入定向指令，并补齐上一轮未执行的工具调用回复。

    上一轮 assistant 若携带 tool_calls 却被判 INVALID，OpenAI 兼容协议要求
    每个 tool_call_id 都要有对应 role="tool" 回复，否则下一轮请求 400；
    这里补齐并把失败原因回写，同时给出修复指令。
    """
    messages: list[ChatMessage] = [ChatMessage(role="system", content=_repair_hint(reason))]
    if state.messages and state.messages[-1].role == "assistant":
        for call in state.messages[-1].tool_calls or []:
            messages.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=call.id,
                    content=f"该工具调用未被执行（{reason}），请重新输出。",
                )
            )
    return messages


def _context_payload(state: ReactGraphState) -> str:
    """把 ReactGraphState 的对话消息归一为 render 阶段可读文本。

    system 消息不重复带入 render（render 会注入自己的 system prompt）；
    assistant 消息仅保留工具调用名，tool 消息保留正文。
    """
    parts: list[str] = []
    for message in state.messages:
        if message.role == "system":
            continue
        content = message.content or ""
        if message.tool_calls:
            calls = " | ".join(call.function.name for call in message.tool_calls)
            content = f"{content} | 工具调用：{calls}".strip(" |")
        if content:
            parts.append(f"{message.role}: {content}")
    return "\n".join(parts)


def build_phase_system_prompt(request: PhaseExecutionRequest) -> str:
    """组装单个阶段的 system 提示（§18.4 LLM Context 组装）。

    装配层系统提示（AGENT.md + SKILL.md + 平台红线）优先；阶段目标、阶段输入与
    兼容期上下文摘要叠加在其上，不替换技能包声明的角色 / 工作流 / 红线。
    结构化上下文投影（`PhaseExecutionRequest.context_messages`）由调用方在本函数
    结果之上拼接，二者只在此处维护一份 system 文本。
    """
    lines: list[str] = []
    if request.system_prompt:
        lines.append(request.system_prompt)
    else:
        lines.append("你是执行当前阶段任务的智能体。")
    lines.append(f"阶段目标：{request.phase_goal}")
    lines.append(f"阶段输入：{request.phase_input or {}}")
    if request.context_summary:
        lines.append(f"上下文摘要：{request.context_summary}")
    lines.append(
        "完成后调用 submit_final_answer 提交最终答案；"
        "多阶段流程的中间候选输出调用 complete_phase；"
        "信息不足调用 request_clarification。"
    )
    return "\n".join(lines)


def _budget_termination(decision: PolicyDecision) -> str:
    if decision.decision == PolicyDecisionType.TERMINATE:
        return f"hard_budget:{decision.reason_code}"
    if decision.decision == PolicyDecisionType.FINALIZE_PARTIAL:
        return f"soft_budget:{decision.reason_code}"
    return ""


def _observation_status(result: ToolResult) -> ObservationStatus:
    if result.ok:
        if not result.content:
            return ObservationStatus.EMPTY
        return ObservationStatus.SUCCEEDED
    return ObservationStatus.FAILED


def _tool_message_content(result: ToolResult, *, max_chars: int) -> str:
    """ToolResult → role="tool" 消息正文：优先正文，失败时给错误/建议，避免空串。"""
    if result.ok:
        content = result.content or "（工具调用完成，无返回内容）"
        return truncate(content, max_length=max_chars)
    parts = [result.message, result.suggestion]
    text = "；".join(part for part in parts if part)
    return truncate(text or "工具调用失败", max_length=max_chars)
