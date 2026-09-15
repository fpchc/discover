"""Bounded ReAct 执行器（react-runtime-v2-architecture §10）。

单一动机：在单个 Phase 内执行有界 ReAct 循环。节点逻辑全部落在此模块，
graph.py 只负责按 §10 拓扑接线（LangGraph 节点 + 条件边）。Policy 不执行工具、
Tool Runtime 不决定阶段完成；执行器只编排。

依赖全部走 Protocol（DIP，CLAUDE.md §6）：LLM 流、ToolBroker、事件发射器
均由组装层注入。ReactGraphState 为子图内状态，跨节点经 LangGraph 传递。
"""

from __future__ import annotations

import time
from collections.abc import Callable

import anyio

from app.environment.tools.models import ToolCallRequest
from app.harness.decision import (
    AgentDecisionType,
    control_tool_specs,
    parse_decision,
)
from app.harness.events.run_events import (
    LLMCallStarted,
    LLMUsageUpdated,
)
from app.harness.execution.pipeline import ToolExecutionRequest
from app.harness.models import (
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
)
from app.harness.policy.budget import check_budget
from app.harness.progress import (
    action_fingerprint,
    evaluate_progress,
)
from app.harness.react.ports import ActionGatewayPort, EventSinkPort, LLMRunnerPort
from app.harness.react.prompt import (
    _budget_termination,
    _context_payload,
    _parse_call_args,
    _repair_messages,
    _to_chat_tool_call,
    _to_stream_call,
    _tool_message_content,
    build_phase_system_prompt,
)
from app.harness.react.state import ReactGraphState
from app.llm.chunks import (
    TextChunk,
    ThinkingChunk,
    ToolCall,
    ToolCallsChunk,
    UsageChunk,
)
from app.llm.models import (
    ChatMessage,
    ChatRequest,
    ChatToolSpec,
)
from app.shared.errors.base import ErrorCategory, PlatformError


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
        actions: ActionGatewayPort,
        events: EventSinkPort,
        progress_threshold: int = 3,
        max_repair_attempts: int = 1,
        display_text: Callable[[str], None] | None = None,
        display_thinking: Callable[[str], None] | None = None,
    ) -> None:
        self._llm = llm
        self._actions = actions
        self._events = events
        self._progress_threshold = progress_threshold
        self._max_repair_attempts = max_repair_attempts
        self._display_text = display_text
        self._display_thinking = display_thinking

    # ---- 节点：react_prepare ----
    async def react_prepare(self, state: ReactGraphState) -> dict[str, object]:
        """初始化阶段消息：优先采用装配层投影结果，缺失时回落系统提示。

        `context_messages` 由 ContextProjector 产出（system + 历史消息 + 独立
        role=user 的当前用户消息），历史 role 语义不再被压平进 system prompt。
        """
        messages = list(state.request.context_messages)
        if not messages:
            messages = [
                ChatMessage(role="system", content=build_phase_system_prompt(state.request))
            ]
        return {"messages": messages, "iteration": 0, "terminate_reason": ""}

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
        return [*control_tool_specs(), *self._actions.exposed_tools()]

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
        """Action Gateway 预检：白名单 + schema + 重复无进展过滤。

        被拒绝的调用也回写为 ``role="tool"`` 消息，保证上一轮 assistant 的
        每个 ``tool_calls`` id 都有对应回复（OpenAI 兼容协议要求 tool_call_id 成对）。
        """
        decision = state.decision
        if decision is None or decision.decision_type != AgentDecisionType.CALL_TOOLS:
            return {"pending_calls": []}
        request = ToolExecutionRequest(
            run_id=state.request.run_id,
            phase_id=state.request.phase_instance_id,
            iteration=state.iteration,
            calls=decision.tool_calls,
            allowed_tools=state.request.allowed_tools,
            budget=state.budget,
            progress=state.progress,
        )
        preflight = await self._actions.preflight(request)
        rejected_messages = [
            ChatMessage(role="tool", tool_call_id=item.call.call_id, content=item.message)
            for item in preflight.rejections
        ]
        return {
            "pending_calls": preflight.pending,
            "action_records": [*state.action_records, *preflight.action_records],
            "messages": [*state.messages, *rejected_messages],
        }

    # ---- 节点：execute_tool ----
    async def execute_tool(self, state: ReactGraphState) -> dict[str, object]:
        """经 Action Gateway 执行已预检通过的工具调用并归一 Observation。

        副作用预记录、真实执行、Observation 归一与产物登记均在 Gateway 内完成；
        本节点只负责把结果映射回图状态与 OpenAI 工具消息。
        """
        request = ToolExecutionRequest(
            run_id=state.request.run_id,
            phase_id=state.request.phase_instance_id,
            iteration=state.iteration,
            calls=state.pending_calls,
            allowed_tools=state.request.allowed_tools,
            budget=state.budget,
            progress=state.progress,
        )
        execution = await self._actions.execute_batch(request)
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
            for result in execution.results
        ]
        joined = "|".join(record.observation_fingerprint for record in execution.observations)
        new_evidence = (
            sum(1 for result in execution.results if result.ok and result.content)
            if joined != state.last_observation_fingerprint
            else 0
        )
        new_artifacts = sum(len(result.produced_files) for result in execution.results)
        return {
            "last_results": execution.results,
            "last_action_fingerprint": "|".join(fingerprints),
            "pending_calls": [],
            "messages": [*state.messages, *tool_messages],
            "observation_records": [*state.observation_records, *execution.observations],
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
            output_schema=state.request.output_schema,
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
            output_schema=state.request.output_schema,
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
