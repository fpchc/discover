"""对话回合执行（v2 Run 生命周期，react-runtime-v2-architecture §16/§17）。

单一动机：把「回合执行」从 HTTP 路由下沉到独立模块（CLAUDE.md §13.1 内聚），
路由只做参数提取与 SSE/JSON 帧映射。本模块负责 RunService 创建 Run、专家
（Agent 技能包 + 单阶段 Bounded ReAct）/ 通用（直接 LLM 流式）两条执行路径、
终态事件发出、历史加载与用量聚合；不感知对外帧格式与落库（DIP）。
"""

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Literal

import anyio

from app.bootstrap.container import AppServices
from app.capabilities.llm.models import ChatMessage, ChatRequest
from app.capabilities.llm.stream_parser import TextChunk, ThinkingChunk, UsageChunk
from app.config.settings import Settings
from app.domain.assistant.models import TargetType
from app.interfaces.schemas import ConversationSession
from app.runtime.agent_runner import AgentAssembler, build_agent_budget, run_agent_turn
from app.runtime.events.emitter import QueueEmitter
from app.runtime.events.run_events import (
    LLMUsageUpdated,
    RunCompleted,
    RunEvent,
    RunFailed,
    ThinkingEnded,
    ThinkingStarted,
)
from app.runtime.models import (
    PhaseExecutionOutcome,
    PhaseExecutionOutcomeType,
    PhaseExecutionRequest,
    TerminationReason,
)
from app.runtime.turn import ActiveTurn
from app.runtime.wiring import LLMRunner, ToolRunner
from app.shared.errors.base import ErrorCategory, PlatformError
from app.shared.utils.sanitize import sanitize_error_message

logger = logging.getLogger(__name__)

_POLL_SECONDS = 0.1

# 直接流式路径的通用系统提示词（不走 ReAct 子图 / 技能包装配）
_GENERIC_SYSTEM_PROMPT = "你是通用对话助手，直接回答用户的问题。"


async def _run_turn_events(
    services: AppServices,
    session: ConversationSession,
    user_input: str,
    *,
    turn: ActiveTurn,
) -> AsyncIterator[RunEvent]:
    """执行单轮并逐个产出 RunEvent（v2 Run 生命周期驱动）。

    绑定专家智能体（assistant_target=expert）→ Agent 技能包路径（装配 agents/ 技能包
    + 单阶段 Bounded ReAct）；未绑定 / 通用对话 → 直接 LLM 流式（喷 RunEvent 展示
    增量）。共用 emitter 骨架：ThinkingStarted 开头、ThinkingEnded + 终态事件收尾。
    """
    emitter = QueueEmitter(services.settings)
    run_done = anyio.Event()

    async def run_turn() -> None:
        logger.info("对话执行开始", extra={"conversation_id": session.conversation_id})
        try:
            run_id = await _create_run(services, session, turn, user_input)
            turn.run_id = run_id
            await emitter.emit(ThinkingStarted(run_id=run_id))
            try:
                await _execute_turn(services, session, user_input, emitter, run_id)
            except PlatformError as exc:
                await _emit_failed(services, emitter, run_id, exc)
            except Exception:
                logger.exception("对话执行异常")
                await _emit_failed(services, emitter, run_id, None)
        finally:
            await emitter.finish()
            run_done.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(emitter.run)
        tg.start_soon(run_turn)
        while True:
            try:
                with anyio.fail_after(_POLL_SECONDS):
                    event = await emitter.get()
            except TimeoutError:
                if run_done.is_set():
                    break
                continue
            except Exception:
                logger.exception("事件队列读取异常")
                raise
            # 不可在 fail_after 取消作用域内 yield：生成器被关闭时 __aexit__
            # 会脱离当前任务的作用域栈，抛出 CancelScope 退出越界 RuntimeError
            yield event
        # 排空队列再退出
        try:
            with anyio.fail_after(_POLL_SECONDS):
                event = await emitter.get()
        except (TimeoutError, Exception):
            pass
        else:
            yield event


async def _create_run(
    services: AppServices,
    session: ConversationSession,
    turn: ActiveTurn,
    user_input: str,
) -> str:
    """创建 Run（RunService.create：快照 + RunStarted 事件 + 执行租约）。

    通用路径无技能信息，skill_id 置 None；专家路径的 skill 在装配阶段解析，
    落入 PhaseExecutionRequest.phase_instance_id（Run 元数据不阻塞执行）。
    """
    target = session.assistant_target
    agent_id = (
        target.id
        if target is not None and target.type == TargetType.EXPERT and target.id is not None
        else "generic"
    )
    state = await services.run_service.create(
        conversation_id=session.conversation_id,
        message_id=turn.message_id,
        account_id=session.account_id,
        agent_id=agent_id,
        skill_id=None,
        user_goal=user_input,
        budget=build_agent_budget(services.settings),
        phases=["main"],
    )
    return state.identity.run_id


async def _execute_turn(
    services: AppServices,
    session: ConversationSession,
    user_input: str,
    emitter: QueueEmitter,
    run_id: str,
) -> str:
    """执行回合主体并发出终态事件（正常 / 失败均以终态 RunEvent 收尾）。

    返回最终正文（blocking 响应 answer 用）；正文展示增量已由执行器 / 直连流式
    经 emitter 打字机推送。思考结束帧先于终态事件，保证 SSE 帧序
    （thinking_ended → message_end / error）。
    """
    started = time.perf_counter()
    try:
        target = session.assistant_target
        if target is not None and target.type == TargetType.EXPERT:
            outcome = await _run_agent_react(services, session, user_input, emitter, run_id)
            answer = _outcome_answer(outcome)
            if answer:
                emitter.text_delta(answer)
            await _emit_thinking_ended(emitter, run_id, started)
            await _emit_agent_terminal(services, emitter, run_id, outcome, answer)
            return answer
        answer = await _run_generic_llm(services, session, user_input, emitter, run_id)
        await _emit_thinking_ended(emitter, run_id, started)
        await _emit_completed(services, emitter, run_id, answer=answer)
        return answer
    except Exception:
        await _emit_thinking_ended(emitter, run_id, started)
        raise


async def _emit_thinking_ended(emitter: QueueEmitter, run_id: str, started: float) -> None:
    """思考结束帧：携带思考耗时（展示分区折叠）。"""
    duration_ms = int((time.perf_counter() - started) * 1000)
    await emitter.emit(ThinkingEnded(run_id=run_id, duration_ms=duration_ms))


async def _emit_agent_terminal(
    services: AppServices,
    emitter: QueueEmitter,
    run_id: str,
    outcome: PhaseExecutionOutcome | None,
    answer: str,
) -> None:
    """专家路径终态：outcome → RunService.complete + RunCompleted 事件（§17.1）。"""
    status, reason, limitations = _agent_terminal(outcome)
    completed, unfinished = _phase_breakdown(status)
    await services.run_service.complete(
        run_id,
        status=status,
        reason=reason,
        final_output=answer,
        completed_phases=completed,
        unfinished_phases=unfinished,
        limitations=limitations,
    )
    await emitter.emit(
        RunCompleted(
            run_id=run_id,
            status=status,
            termination_reason=reason,
            final_output=answer,
            completed_phases=completed,
            unfinished_phases=unfinished,
            limitations=limitations,
        )
    )


async def _emit_completed(
    services: AppServices,
    emitter: QueueEmitter,
    run_id: str,
    *,
    answer: str,
) -> None:
    """通用路径终态：正常完成（succeeded / COMPLETED）。"""
    completed, unfinished = _phase_breakdown("succeeded")
    await services.run_service.complete(
        run_id,
        status="succeeded",
        reason=TerminationReason.COMPLETED,
        final_output=answer,
        completed_phases=completed,
        unfinished_phases=unfinished,
        limitations=[],
    )
    await emitter.emit(
        RunCompleted(
            run_id=run_id,
            status="succeeded",
            termination_reason=TerminationReason.COMPLETED,
            final_output=answer,
            completed_phases=completed,
            unfinished_phases=unfinished,
            limitations=[],
        )
    )


async def _emit_failed(
    services: AppServices,
    emitter: QueueEmitter,
    run_id: str,
    exc: PlatformError | None,
) -> None:
    """失败终态：RunService.fail + RunFailed 事件（无可交付结果或不可恢复错误）。"""
    if exc is None:
        category = ErrorCategory.SERVER
        message = "内部错误"
        recoverable = False
    else:
        category = exc.category
        message = sanitize_error_message(
            str(exc), max_length=services.settings.error_message_max_chars
        )
        recoverable = exc.retryable
    await services.run_service.fail(
        run_id,
        reason=TerminationReason.INTERNAL_ERROR,
        message=message,
        error_category=category,
    )
    await emitter.emit(
        RunFailed(
            run_id=run_id,
            termination_reason=TerminationReason.INTERNAL_ERROR,
            error_category=category,
            message=message,
            recoverable=recoverable,
        )
    )


def _phase_breakdown(status: Literal["succeeded", "partial"]) -> tuple[list[str], list[str]]:
    """单阶段 Run 的阶段完成分解：成功 → 全部完成；部分 → 主阶段未完成。"""
    if status == "succeeded":
        return ["main"], []
    return [], ["main"]


def _agent_terminal(
    outcome: PhaseExecutionOutcome | None,
) -> tuple[Literal["succeeded", "partial"], TerminationReason, list[str]]:
    """PhaseExecutionOutcome → Run 终态（status / reason / limitations，§17.1）。"""
    if outcome is None:
        return "partial", TerminationReason.NO_PROGRESS, ["无执行结果"]
    if outcome.outcome_type in (
        PhaseExecutionOutcomeType.FINAL_PROPOSED,
        PhaseExecutionOutcomeType.CANDIDATE_COMPLETED,
        PhaseExecutionOutcomeType.INPUT_REQUIRED,
    ):
        return "succeeded", TerminationReason.COMPLETED, outcome.limitations
    if outcome.outcome_type == PhaseExecutionOutcomeType.PARTIAL_NO_PROGRESS:
        return "partial", TerminationReason.NO_PROGRESS, outcome.limitations or ["无进展，部分完成"]
    if outcome.outcome_type == PhaseExecutionOutcomeType.PARTIAL_BUDGET:
        return (
            "partial",
            TerminationReason.TOKEN_BUDGET,
            outcome.limitations or ["预算受限，部分完成"],
        )
    return "partial", TerminationReason.CONTRACT_FAILED, outcome.limitations


async def _load_history(services: AppServices, session: ConversationSession) -> list[ChatMessage]:
    """加载会话历史为模型上下文（conversation_service 缺失时降级为空）。"""
    if services.conversation_service is None:
        return []
    return await services.conversation_service.get_history_messages(
        account_id=session.account_id,
        conversation_id=session.conversation_id,
        limit=services.settings.history_max_messages,
    )


def _accumulate_usage(acc: dict[str, int], chunk: UsageChunk) -> dict[str, int]:
    """把单次 UsageChunk 累加进回合用量统计。"""
    return {
        "input": acc["input"] + chunk.input_tokens,
        "output": acc["output"] + chunk.output_tokens,
        "total": acc["total"] + chunk.total_tokens,
        "cached_read": acc["cached_read"] + chunk.cached_read_tokens,
        "cached_write": acc["cached_write"] + chunk.cached_write_tokens,
    }


def _history_summary(history: list[ChatMessage], settings: Settings) -> str:
    """会话历史 → ReAct 上下文摘要（限消息数 / 总字符，防上下文撑爆）。"""
    recent = history[-settings.agent_context_summary_max_messages :]
    lines = [f"{msg.role}: {msg.content}" for msg in recent]
    summary = "\n".join(lines)
    return summary[: settings.agent_context_summary_max_chars]


def _outcome_answer(outcome: PhaseExecutionOutcome | None) -> str:
    """PhaseExecutionOutcome → 最终正文（FINAL_PROPOSED 取 answer；CANDIDATE 序列化）。"""
    if outcome is None:
        return ""
    if outcome.answer:
        return outcome.answer
    if outcome.candidate_output:
        return json.dumps(outcome.candidate_output, ensure_ascii=False)
    return ""


async def _run_agent_react(
    services: AppServices,
    session: ConversationSession,
    user_input: str,
    emitter: QueueEmitter,
    run_id: str,
) -> PhaseExecutionOutcome | None:
    """装配 agents 技能包 → 构建 PhaseExecutionRequest → 跑单阶段 Bounded ReAct。

    events=emitter：执行器 RunEvent（LLMUsageUpdated / ActionProposed 等）直接进入
    会话事件流，SSE 经 map_run_event 归一、TurnRecorder 聚合用量；展示增量继续走
    display_text / display_thinking（emitter.text_delta / thinking_delta）。
    """
    assert services.registry is not None
    assert services.workspaces is not None
    assert services.llm is not None
    assert services.providers is not None
    assert services._resolve_api_key is not None
    assembler = AgentAssembler(
        registry=services.registry,
        workspaces=services.workspaces,
        mcp_manager=services.mcp_manager,
        script_executor=services.script_executor,
        settings=services.settings,
    )
    result = await assembler.resolve_and_assemble(
        assistant_target=session.assistant_target,
        account_id=session.account_id,
        session_id=session.conversation_id,
    )
    if result is None:
        raise PlatformError("智能体或技能装配失败", category=ErrorCategory.SERVER, retryable=False)
    broker = result.broker
    try:
        llm = LLMRunner(
            client=services.llm,
            providers=services.providers,
            resolve_api_key=services._resolve_api_key,
            settings=services.settings,
        )
        tools = ToolRunner(broker)
        # 阶段白名单取目录全集（Tier 0 + Tier 1 + Tier 2），而非仅已暴露集合：
        # describe_tool 只是按需展开参数约束，不是调用授权；否则懒加载的 Tier 2 工具
        # 会被 preflight 误判为「不在阶段白名单」，模型陷入盲搜死循环、正文始终为空。
        allowed_tools = tools.catalog_tool_names()
        history = await _load_history(services, session)
        request = PhaseExecutionRequest(
            run_id=run_id,
            phase_instance_id=result.plan.skill_id,
            phase_goal=result.plan.skill_id,
            system_prompt=result.plan.system_prompt,
            phase_input={"user_goal": user_input},
            context_summary=_history_summary(history, services.settings),
            allowed_tools=allowed_tools,
            # 全局开关与装配层 thinking_preference 共同决定是否开启思考通道
            thinking_enabled=(
                services.settings.thinking_enabled and result.plan.thinking_preference != "off"
            ),
            tool_message_max_chars=services.settings.agent_tool_message_max_chars,
            budget=build_agent_budget(services.settings),
        )
        return await run_agent_turn(
            llm=llm,
            tools=tools,
            events=emitter,
            request=request,
            display_text=emitter.text_delta,
            display_thinking=emitter.thinking_delta,
        )
    finally:
        await broker.close()


async def _run_generic_llm(
    services: AppServices,
    session: ConversationSession,
    user_input: str,
    emitter: QueueEmitter,
    run_id: str,
) -> str:
    """通用对话：直接流式调用 LLM，分片映射为 RunEvent 展示增量并聚合用量。"""
    assert services.llm is not None
    assert services.providers is not None
    assert services._resolve_api_key is not None
    llm = LLMRunner(
        client=services.llm,
        providers=services.providers,
        resolve_api_key=services._resolve_api_key,
        settings=services.settings,
    )
    messages = [ChatMessage(role="system", content=_GENERIC_SYSTEM_PROMPT)]
    history = await _load_history(services, session)
    messages.extend(history)
    messages.append(ChatMessage(role="user", content=user_input))
    usage: dict[str, int] = {
        "input": 0,
        "output": 0,
        "total": 0,
        "cached_read": 0,
        "cached_write": 0,
    }
    text_parts: list[str] = []
    async for chunk in llm.stream(request=ChatRequest(messages=messages, thinking=True)):
        if isinstance(chunk, TextChunk):
            text_parts.append(chunk.text)
            emitter.text_delta(chunk.text)
        elif isinstance(chunk, ThinkingChunk):
            emitter.thinking_delta(chunk.text)
        elif isinstance(chunk, UsageChunk):
            usage = _accumulate_usage(usage, chunk)
    await emitter.emit(LLMUsageUpdated(run_id=run_id, usage=usage))
    return "".join(text_parts)
