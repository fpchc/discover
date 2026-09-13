"""对话回合的两条执行路径：专家（Agent 技能包 + Bounded ReAct）与通用（直接流式）。

单一动机：把 `run_turn.py` 里的执行主体抽出，保留该文件只做 Run 生命周期编排与
终态事件发射。本模块只依赖 harness / llm / environment 与上下文装配，不感知
SSE 帧与落库。
"""

from __future__ import annotations

from app.application.chat.turn_context import TurnContextRequest, build_turn_context
from app.application.dto import ConversationSession
from app.application.services import AppServices
from app.config.settings import Settings
from app.harness.agent_runner import (
    AgentAssembler,
    build_agent_budget,
    build_workflow_definition,
    run_agent_turn,
    run_skill_workflow,
)
from app.harness.events.emitter import QueueEmitter
from app.harness.events.run_events import LLMUsageUpdated
from app.harness.models import PhaseExecutionOutcome, PhaseExecutionRequest
from app.harness.react.prompt import build_phase_system_prompt
from app.harness.skill.manifest import ThinkingPreference
from app.harness.wiring import LLMRunner, ToolRunner
from app.llm.chunks import TextChunk, ThinkingChunk, UsageChunk
from app.llm.models import ChatRequest
from app.shared.errors.base import ErrorCategory, PlatformError

# 直接流式路径的通用系统提示词（不走 ReAct 子图 / 技能包装配）
_GENERIC_SYSTEM_PROMPT = "你是通用对话助手，直接回答用户的问题。"


def _accumulate_usage(acc: dict[str, int], chunk: UsageChunk) -> dict[str, int]:
    """把单次 UsageChunk 累加进回合用量统计。"""
    return {
        "input": acc["input"] + chunk.input_tokens,
        "output": acc["output"] + chunk.output_tokens,
        "total": acc["total"] + chunk.total_tokens,
        "cached_read": acc["cached_read"] + chunk.cached_read_tokens,
        "cached_write": acc["cached_write"] + chunk.cached_write_tokens,
    }


def _resolve_thinking_budget(
    preference: ThinkingPreference | None, settings: Settings
) -> int | None:
    """thinking_preference → thinking_budget（思维链 token 上限）。

    off → 不限制（思考已关闭）；low/medium 映射到配置的 token 上限，避免 qwen3
    默认 131072 的思考上限导致单轮思考过长、前端长时间无过程可看；high → 不限制，
    保留深度思考能力（如账期评估）。
    """
    if preference is None or preference == "off":
        return None
    budget = {
        "low": settings.llm_thinking_budget_low,
        "medium": settings.llm_thinking_budget_medium,
        "high": settings.llm_thinking_budget_high,
    }.get(preference, settings.llm_thinking_budget_low)
    return budget if budget > 0 else None


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
    assert services.resolve_api_key is not None
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
            resolve_api_key=services.resolve_api_key,
            settings=services.settings,
        )
        tools = ToolRunner(broker)
        # 阶段白名单取目录全集（Tier 0 + Tier 1 + Tier 2），而非仅已暴露集合：
        # describe_tool 只是按需展开参数约束，不是调用授权；否则懒加载的 Tier 2 工具
        # 会被 preflight 误判为「不在阶段白名单」，模型陷入盲搜死循环、正文始终为空。
        allowed_tools = tools.catalog_tool_names()
        # 结构化上下文装配（agent-context-plane-spec §5.1/§5.4）：历史以 role
        # 语义进入消息序列，当前用户输入独立成 role=user，摘要仅作兼容字段。
        turn = await build_turn_context(
            services,
            TurnContextRequest(
                session=session,
                user_input=user_input,
                run_id=run_id,
                phase_instance_id=result.plan.skill_id,
                expert=True,
            ),
        )
        request = PhaseExecutionRequest(
            run_id=run_id,
            phase_instance_id=result.plan.skill_id,
            phase_goal=result.plan.skill_id,
            system_prompt=result.plan.system_prompt,
            phase_input={"user_goal": user_input},
            context_summary=turn.history_summary,
            allowed_tools=allowed_tools,
            # 全局开关与装配层 thinking_preference 共同决定是否开启思考通道
            thinking_enabled=(
                services.settings.thinking_enabled and result.plan.thinking_preference != "off"
            ),
            thinking_budget=_resolve_thinking_budget(
                result.plan.thinking_preference, services.settings
            ),
            tool_message_max_chars=services.settings.agent_tool_message_max_chars,
            budget=build_agent_budget(services.settings, result.plan),
        )
        request = request.model_copy(
            update={
                "context_messages": turn.messages(system_prompt=build_phase_system_prompt(request))
            }
        )
        workflow = build_workflow_definition(result.plan)
        if workflow is not None:
            return await run_skill_workflow(
                llm=llm,
                tools=tools,
                events=emitter,
                request=request,
                definition=workflow,
                display_text=emitter.text_delta,
                display_thinking=emitter.thinking_delta,
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
    assert services.resolve_api_key is not None
    llm = LLMRunner(
        client=services.llm,
        providers=services.providers,
        resolve_api_key=services.resolve_api_key,
        settings=services.settings,
    )
    # 与专家路径共用同一装配与投影规则（agent-context-plane-spec §5.4）
    turn = await build_turn_context(
        services,
        TurnContextRequest(session=session, user_input=user_input, run_id=run_id),
    )
    messages = turn.messages(system_prompt=_GENERIC_SYSTEM_PROMPT)
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
