"""Bounded ReAct 执行器（react-runtime-v2-architecture §10）。

单一动机：在单个 Phase 内执行有界 ReAct 循环。节点逻辑全部落在此模块，
graph.py 只负责按 §10 拓扑接线（LangGraph 节点 + 条件边）。Policy 不执行工具、
Tool Runtime 不决定阶段完成；执行器只编排。

依赖全部走 Protocol（DIP，CLAUDE.md §6）：LLM 流、ToolBroker、事件发射器
均由组装层注入。ReactGraphState 为子图内状态，跨节点经 LangGraph 传递。
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Protocol

import anyio
from pydantic import BaseModel, Field

from app.capabilities.llm.models import (
    ChatMessage,
    ChatRequest,
    ChatToolCall,
    ChatToolCallFunction,
    ChatToolSpec,
)
from app.capabilities.llm.stream_parser import (
    SemanticChunk,
    TextChunk,
    ThinkingChunk,
    ToolCall,
    ToolCallsChunk,
    UsageChunk,
)
from app.capabilities.tools.broker import ToolCallRequest, ToolResult
from app.capabilities.tools.descriptor import ToolDescriptor
from app.harness.events.run_events import (
    ActionProposed,
    LLMCallStarted,
    LLMUsageUpdated,
    RunEvent,
)
from app.harness.models import (
    ActionRecord,
    ActionStatus,
    BudgetState,
    ObservationRecord,
    ObservationStatus,
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
    ProgressState,
)
from app.harness.policy.action import check_action
from app.harness.policy.budget import check_budget
from app.harness.policy.models import PolicyDecision, PolicyDecisionType
from app.harness.react.decision import (
    AgentDecision,
    AgentDecisionType,
    control_tool_specs,
    parse_decision,
)
from app.harness.react.progress import (
    action_fingerprint,
    evaluate_progress,
    observation_fingerprint,
)
from app.shared.errors.base import ErrorCategory, PlatformError
from app.shared.utils.sanitize import truncate


class LLMRunnerPort(Protocol):
    """LLM 流式调用抽象：隐藏 provider / api_key 解析（组装层适配）。

    声明为异步生成器签名（def + AsyncIterator），供 ``async for`` 消费。
    """

    def stream(self, *, request: ChatRequest) -> AsyncIterator[SemanticChunk]: ...


class ToolRunnerPort(Protocol):
    """工具执行抽象：目录查询 + 分发（ToolBroker 实现，唯一出口）。"""

    def exposed_tools(self) -> list[ChatToolSpec]: ...
    def get_descriptor(self, name: str) -> ToolDescriptor | None: ...
    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]: ...


class EventSinkPort(Protocol):
    """Run 事件发射抽象：SSE / 审计 / 观测统一出口。"""

    async def emit(self, event: RunEvent) -> None: ...


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


class AgentDurationExceeded(PlatformError):
    """回合总时长硬预算超限：单次 LLM 调用突破剩余时长预算即中断回合。

    预算 duration_seconds 只累计**已完成**的调用；进行中的慢/挂死调用若不受限，
    整个回合会无界运行（check_budget 只在迭代间隙检查，无法中断进行中的调用）。
    call_llm 用「剩余时长」包裹流式调用，超限即终止（已展示的部分内容仍经 SSE
    到达前端，落库由 record_turn 兜底）。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ErrorCategory.TIMEOUT, retryable=False)


class BoundedReActExecutor:
    """单 Phase 有界 ReAct 执行器：图节点方法实现（§10 拓扑）。"""

    def __init__(
        self,
        *,
        llm: LLMRunnerPort,
        tools: ToolRunnerPort,
        events: EventSinkPort,
        progress_threshold: int = 3,
        max_repair_attempts: int = 1,
        display_text: Callable[[str], None] | None = None,
        display_thinking: Callable[[str], None] | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._events = events
        self._progress_threshold = progress_threshold
        self._max_repair_attempts = max_repair_attempts
        self._display_text = display_text
        self._display_thinking = display_thinking

    # ---- 节点：react_prepare ----
    async def react_prepare(self, state: ReactGraphState) -> dict[str, object]:
        system = ChatMessage(role="system", content=self._system_prompt(state))
        return {"messages": [system], "iteration": 0, "terminate_reason": ""}

    def _system_prompt(self, state: ReactGraphState) -> str:
        request = state.request
        lines: list[str] = []
        if request.system_prompt:
            # 装配层系统提示（AGENT.md + SKILL.md + 平台红线）：阶段信息叠加在其上，
            # 不替换技能包声明的角色 / 工作流 / 红线（§18.4 LLM Context 组装）。
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

    # ---- 节点：check_budget ----
    async def check_budget(self, state: ReactGraphState) -> dict[str, object]:
        decision = check_budget(state.budget)
        reason = _budget_termination(decision)
        return {"budget": decision.budget_snapshot or state.budget, "terminate_reason": reason}

    # ---- 节点：call_llm ----
    async def call_llm(self, state: ReactGraphState) -> dict[str, object]:
        start = time.perf_counter()
        await self._events.emit(
            LLMCallStarted(
                run_id=state.request.run_id,
                phase_id=state.request.phase_instance_id,
                call_index=state.iteration,
            )
        )
        request = ChatRequest(
            messages=state.messages,
            tools=self._all_tool_specs(),
            thinking=state.request.thinking_enabled,
            thinking_budget=state.request.thinking_budget,
        )
        text_parts: list[str] = []
        tool_calls_accum: list[ToolCall] = []
        usage = {"input": 0, "output": 0, "total": 0, "cached_read": 0, "cached_write": 0}
        # 用「剩余时长预算」包裹本次调用：duration_seconds 只累计已完成调用，
        # 不包裹的话单次慢/挂死调用会让整个回合无界运行（check_budget 只在迭代
        # 间隙检查，无法中断进行中的调用）。超限即终止回合（AgentDurationExceeded）。
        remaining_seconds = (
            state.budget.limits.max_duration_seconds - state.budget.usage.duration_seconds
        )
        try:
            with anyio.fail_after(max(remaining_seconds, 1.0)):
                async for chunk in self._llm.stream(request=request):
                    if isinstance(chunk, TextChunk):
                        # 专家 ReAct 路径：中间 TextChunk 只作为 assistant 消息与
                        # parse_decision 的草稿，不推送到可见正文；最终 answer 由
                        # chat_execution._execute_turn 在拿到 outcome.answer 后统一推送。
                        text_parts.append(chunk.text)
                    elif isinstance(chunk, ThinkingChunk):
                        if self._display_thinking is not None:
                            self._display_thinking(chunk.text)
                    elif isinstance(chunk, ToolCallsChunk):
                        tool_calls_accum = chunk.tool_calls
                    elif isinstance(chunk, UsageChunk):
                        usage = self._add_usage(usage, chunk)
        except TimeoutError as exc:
            raise AgentDurationExceeded(
                "回合总时长超限，已中断执行（LLM 调用超过剩余时长预算）"
            ) from exc
        duration = int((time.perf_counter() - start) * 1000)
        await self._events.emit(
            LLMUsageUpdated(
                run_id=state.request.run_id,
                phase_id=state.request.phase_instance_id,
                call_index=state.iteration,
                usage=usage,
            )
        )
        assistant = ChatMessage(
            role="assistant",
            content="".join(text_parts) or None,
            tool_calls=[_to_chat_tool_call(call) for call in tool_calls_accum] or None,
        )
        pending = [
            ToolCallRequest(
                call_id=call.id or "",
                tool_name=call.name or "",
                arguments=_parse_call_args(call),
            )
            for call in tool_calls_accum
        ]
        budget = state.budget.model_copy(
            update={
                "usage": state.budget.usage.model_copy(
                    update={
                        "iterations": state.budget.usage.iterations + 1,
                        "llm_calls": state.budget.usage.llm_calls + 1,
                        "total_tokens": state.budget.usage.total_tokens + usage["total"],
                        "input_tokens": state.budget.usage.input_tokens + usage["input"],
                        "duration_seconds": state.budget.usage.duration_seconds + duration / 1000.0,
                    }
                )
            }
        )
        return {
            "messages": [*state.messages, assistant],
            "pending_calls": pending,
            "text_parts": state.text_parts + "".join(text_parts),
            "budget": budget,
            "iteration": state.iteration + 1,
        }

    def _all_tool_specs(self) -> list[ChatToolSpec]:
        return [*control_tool_specs(), *self._tools.exposed_tools()]

    @staticmethod
    def _add_usage(acc: dict[str, int], chunk: UsageChunk) -> dict[str, int]:
        return {
            "input": acc["input"] + chunk.input_tokens,
            "output": acc["output"] + chunk.output_tokens,
            "total": acc["total"] + chunk.total_tokens,
            "cached_read": acc["cached_read"] + chunk.cached_read_tokens,
            "cached_write": acc["cached_write"] + chunk.cached_write_tokens,
        }

    # ---- 节点：parse_decision ----
    async def parse_decision(self, state: ReactGraphState) -> dict[str, object]:
        tool_calls = [_to_stream_call(call) for call in state.pending_calls]
        decision = parse_decision(tool_calls, text_only=bool(state.text_parts) and not tool_calls)
        return {"decision": decision}

    # ---- 节点：validate_decision ----
    async def validate_decision(self, state: ReactGraphState) -> dict[str, object]:
        """决策校验：INVALID 触发有界格式修复（§10.1 规则⑤），其他交由条件边路由。"""
        decision = state.decision
        if decision is None:
            return {"terminate_reason": "no_decision"}
        if decision.decision_type == AgentDecisionType.INVALID_DECISION:
            if state.repair_attempts < self._max_repair_attempts:
                return {
                    "repair_attempts": state.repair_attempts + 1,
                    "terminate_reason": "format_repair",
                    "messages": [
                        *state.messages,
                        *_repair_messages(state, decision.invalid_reason),
                    ],
                }
            return {"terminate_reason": f"repair_exhausted:{decision.invalid_reason}"}
        return {}

    # ---- 节点：preflight_action ----
    async def preflight_action(self, state: ReactGraphState) -> dict[str, object]:
        """Action Policy 预检：白名单 + schema + 重复无进展过滤，产出 ActionRecord。

        被 Policy 拒绝的调用也回写为 ``role="tool"`` 消息，保证上一轮 assistant 的
        每个 ``tool_calls`` id 都有对应回复（OpenAI 兼容协议要求 tool_call_id 成对）。
        """
        decision = state.decision
        if decision is None or decision.decision_type != AgentDecisionType.CALL_TOOLS:
            return {"pending_calls": []}
        allowed: list[ToolCallRequest] = []
        records: list[ActionRecord] = []
        rejected_messages: list[ChatMessage] = []
        for index, call in enumerate(decision.tool_calls):
            fingerprint = action_fingerprint(
                call.tool_name, call.arguments, phase_id=state.request.phase_instance_id
            )
            await self._events.emit(
                ActionProposed(
                    run_id=state.request.run_id,
                    phase_id=state.request.phase_instance_id,
                    tool_name=call.tool_name,
                    args_summary=str(call.arguments)[:200],
                    fingerprint=fingerprint,
                )
            )
            check = check_action(
                descriptor=self._tools.get_descriptor(call.tool_name),
                arguments=call.arguments,
                allowed_tools=state.request.allowed_tools,
                recent_actions=state.action_records,
                progress=state.progress,
                progress_threshold=self._progress_threshold,
            )
            record = ActionRecord(
                action_id=f"{state.request.phase_instance_id}.{state.iteration}.{index}",
                step_id=f"{state.iteration}.{index}",
                tool_name=call.tool_name,
                arguments=dict(call.arguments),
                arguments_fingerprint=fingerprint,
                status=(
                    ActionStatus.ALLOWED
                    if check.decision == PolicyDecisionType.ALLOW
                    else ActionStatus.REJECTED
                ),
            )
            records.append(record)
            if check.decision == PolicyDecisionType.ALLOW:
                allowed.append(call)
            else:
                rejected_messages.append(
                    ChatMessage(
                        role="tool",
                        tool_call_id=call.call_id,
                        content=check.display_message or check.reason_code or "调用被拒绝",
                    )
                )
        return {
            "pending_calls": allowed,
            "action_records": [*state.action_records, *records],
            "messages": [*state.messages, *rejected_messages],
        }

    # ---- 节点：execute_tool ----
    async def execute_tool(self, state: ReactGraphState) -> dict[str, object]:
        results = await self._tools.execute(state.pending_calls)
        fingerprints = [
            action_fingerprint(
                call.tool_name, call.arguments, phase_id=state.request.phase_instance_id
            )
            for call in state.pending_calls
        ]
        tool_messages = [
            ChatMessage(
                role="tool",
                tool_call_id=result.call_id,
                content=_tool_message_content(
                    result, max_chars=state.request.tool_message_max_chars
                ),
            )
            for result in results
        ]
        return {
            "last_results": results,
            "last_action_fingerprint": "|".join(fingerprints),
            "pending_calls": [],
            "messages": [*state.messages, *tool_messages],
        }

    # ---- 节点：normalize_observation ----
    async def normalize_observation(self, state: ReactGraphState) -> dict[str, object]:
        """ToolResult → ObservationRecord（指纹 / 状态 / 错误分类），并做进展增量统计。

        新增证据只在 Observation 指纹与上次不同时计数（§12.4「没有新增证据」判定）；
        相同结果的重复返回不视为新证据，否则 no_progress 永不触发。
        """
        records: list[ObservationRecord] = []
        new_artifacts = 0
        obs_fps: list[str] = []
        for result in state.last_results:
            status = _observation_status(result)
            fingerprint = observation_fingerprint(
                ok=result.ok,
                content_summary=result.content,
                error_category=result.error_category,
                artifact_summary=",".join(result.produced_files),
            )
            records.append(
                ObservationRecord(
                    observation_id=f"{state.request.phase_instance_id}.{state.iteration}.{result.call_id}",
                    step_id=f"{state.iteration}.{result.call_id}",
                    action_id=result.call_id,
                    status=status,
                    content_summary=result.content[:500],
                    observation_fingerprint=fingerprint,
                    error_category=result.error_category,
                    artifact_ids=list(result.produced_files),
                    truncated=result.truncated,
                    progress_delta=1 if result.ok and result.content else 0,
                )
            )
            obs_fps.append(fingerprint)
            if result.produced_files:
                new_artifacts += len(result.produced_files)
        joined = "|".join(obs_fps) if obs_fps else ""
        new_evidence = (
            sum(1 for result in state.last_results if result.ok and result.content)
            if joined != state.last_observation_fingerprint
            else 0
        )
        return {
            "observation_records": [*state.observation_records, *records],
            "last_observation_fingerprint": joined,
            "new_evidence_count": new_evidence,
            "new_artifact_count": new_artifacts,
        }

    # ---- 节点：evaluate_progress ----
    async def evaluate_progress(self, state: ReactGraphState) -> dict[str, object]:
        """§12.4 六条件无进展判定，更新 ProgressState 并决定是否终止。"""
        progress, stalled = evaluate_progress(
            state.progress,
            action_fp=state.last_action_fingerprint,
            observation_fp=state.last_observation_fingerprint,
            new_evidence_count=state.new_evidence_count,
            new_artifact_count=state.new_artifact_count,
            contract_improved=False,
            threshold=self._progress_threshold,
        )
        return {
            "progress": progress,
            "terminate_reason": "no_progress" if stalled else "",
        }

    # ---- 节点：phase_contract ----
    async def phase_contract(self, state: ReactGraphState) -> dict[str, object]:
        """COMPLETE_PHASE → 固化 CANDIDATE_COMPLETED（Contract 校验在 W5 接入）。"""
        decision = state.decision
        params = decision.complete_phase if decision is not None else None
        outcome = PhaseExecutionOutcome(
            outcome_type=PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
            candidate_output=params.output if params is not None else None,
            context_payload=_context_payload(state),
            usage_snapshot=state.budget.usage,
            budget_snapshot=state.budget,
            observation_ids=[record.observation_id for record in state.observation_records],
            limitations=params.limitations if params is not None else [],
            reason_code="candidate_completed",
        )
        return {"outcome": outcome}

    # ---- 节点：output_contract ----
    async def output_contract(self, state: ReactGraphState) -> dict[str, object]:
        """FINAL_ANSWER → 固化 FINAL_PROPOSED（Output Contract 在 W5 接入）。"""
        decision = state.decision
        params = decision.final_answer if decision is not None else None
        outcome = PhaseExecutionOutcome(
            outcome_type=PhaseExecutionOutcomeType.FINAL_PROPOSED,
            answer=params.answer if params is not None else "",
            context_payload=_context_payload(state),
            usage_snapshot=state.budget.usage,
            budget_snapshot=state.budget,
            observation_ids=[record.observation_id for record in state.observation_records],
            limitations=params.limitations if params is not None else [],
            reason_code="final_proposed",
        )
        return {"outcome": outcome}

    # ---- 节点：finalize ----
    async def finalize(self, state: ReactGraphState) -> dict[str, object]:
        decision = state.decision
        if decision is not None and decision.decision_type == AgentDecisionType.NEED_CLARIFICATION:
            params = decision.clarification
            outcome = PhaseExecutionOutcome(
                outcome_type=PhaseExecutionOutcomeType.INPUT_REQUIRED,
                answer=params.question if params is not None else "",
                context_payload=_context_payload(state),
                usage_snapshot=state.budget.usage,
                budget_snapshot=state.budget,
                limitations=params.missing_fields if params is not None else [],
                reason_code="input_required",
            )
            return {"outcome": outcome}
        # 只有真正的预算软/硬超限才归类 PARTIAL_BUDGET；格式修复耗尽 / 无决策
        # 属于「模型未能产出有效工具决策」的无进展，归类 PARTIAL_NO_PROGRESS，
        # 避免误导前端显示成 token_budget（预算其实远未用尽）。
        _no_progress_marks = ("no_progress", "repair_exhausted", "no_decision")
        partial = (
            PhaseExecutionOutcomeType.PARTIAL_NO_PROGRESS
            if any(mark in state.terminate_reason for mark in _no_progress_marks)
            else PhaseExecutionOutcomeType.PARTIAL_BUDGET
        )
        outcome = PhaseExecutionOutcome(
            outcome_type=partial,
            answer=state.text_parts or "",
            context_payload=_context_payload(state),
            usage_snapshot=state.budget.usage,
            budget_snapshot=state.budget,
            observation_ids=[record.observation_id for record in state.observation_records],
            limitations=["预算或进展受限，部分完成"],
            reason_code=state.terminate_reason,
        )
        return {"outcome": outcome}


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
