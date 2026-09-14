"""技能包调试：草稿预览对话 + 工具冒烟测试。

复用 harness 的 Bounded ReAct / Workflow 执行器与上下文装配，只把事件发射
换成内存收集器，产出完整 RunEvent trace 供管理端排查。真实数据源按用户决策
直接放行（不 mock、不阻断）。
"""

from __future__ import annotations

import json
import uuid
from typing import Protocol

from app.application.chat.turn_context import TurnContextRequest, build_turn_context
from app.application.chat.turn_paths import _resolve_thinking_budget
from app.application.dto.conversations import ConversationSession
from app.application.dto.skill_packages import (
    DebugRunEvent,
    PreviewResult,
    ToolSmokeResult,
)
from app.application.services import AppServices
from app.environment.tools.models import ToolCallRequest, ToolDescriptor, ToolResult
from app.harness.agent_runner import (
    AgentAssembler,
    build_agent_budget,
    build_workflow_definition,
    run_agent_turn,
    run_skill_workflow,
)
from app.harness.events.run_events import RunEvent
from app.harness.models import PhaseExecutionOutcome, PhaseExecutionRequest
from app.harness.react.prompt import build_phase_system_prompt
from app.harness.targets import AssistantTarget, TargetType
from app.harness.wiring import LLMRunner, ToolRunner
from app.shared.errors.base import BadRequestError, NotFoundError


class _SmokeCatalog(Protocol):
    """冒烟测试所需的工具目录查询能力（ToolBroker / ToolRunner 均满足）。"""

    def get_descriptor(self, qualified_name: str) -> ToolDescriptor | None: ...
    def catalog_tool_names(self) -> list[str]: ...


class _CollectingSink:
    """把 RunEvent 收进内存列表的发射器（调试用）。"""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    async def emit(self, event: RunEvent) -> None:
        self.events.append(event)


def resolve_smoke_tool(catalog: _SmokeCatalog, tool_name: str) -> str:
    """把工具名解析为目录限定名（支持限定名或短名唯一匹配）。"""
    if catalog.get_descriptor(tool_name) is not None:
        return tool_name
    candidates = [
        name
        for name in catalog.catalog_tool_names()
        if name == tool_name or name.rsplit(".", 1)[-1] == tool_name
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise BadRequestError(f"工具名歧义：{', '.join(sorted(candidates))}")
    raise NotFoundError(f"工具不在目录：{tool_name}")


def _serialize(event: RunEvent, seq: int) -> DebugRunEvent:
    return DebugRunEvent(
        seq=seq,
        event_type=type(event).__name__,
        payload=event.model_dump(mode="json", exclude={"seq"}),
    )


def _outcome_answer(outcome: PhaseExecutionOutcome | None) -> str:
    if outcome is None:
        return ""
    if outcome.answer:
        return outcome.answer
    if outcome.candidate_output:
        return json.dumps(outcome.candidate_output, ensure_ascii=False)
    return ""


def _smoke_result(result: ToolResult) -> ToolSmokeResult:
    return ToolSmokeResult(
        call_id=result.call_id,
        tool_name=result.tool_name,
        ok=result.ok,
        content=result.content,
        error_category=result.error_category.value if result.error_category else None,
        message=result.message,
        suggestion=result.suggestion,
        duration_ms=result.duration_ms,
        truncated=result.truncated,
        produced_files=list(result.produced_files),
    )


async def run_draft_preview(
    services: AppServices,
    package_id: uuid.UUID,
    *,
    user_input: str,
    account_id: str,
) -> PreviewResult:
    """对草稿版本跑一次真实 ReAct/Workflow 对话，返回正文 + 事件 trace。"""
    assert services.skill_packages is not None
    assert services.registry is not None
    assert services.workspaces is not None
    assert services.llm is not None
    assert services.providers is not None
    assert services.resolve_api_key is not None
    package = await services.skill_packages.load_draft_package(package_id)
    assembler = AgentAssembler(
        registry=services.registry,
        workspaces=services.workspaces,
        mcp_manager=services.mcp_manager,
        script_executor=services.script_executor,
        settings=services.settings,
    )
    run_id = f"debug-{uuid.uuid4().hex}"
    session_id = f"debug-{uuid.uuid4().hex}"
    assembled = await assembler.assemble_from_package(
        package=package, account_id=account_id, session_id=session_id
    )
    broker = assembled.broker
    try:
        llm = LLMRunner(
            client=services.llm,
            providers=services.providers,
            resolve_api_key=services.resolve_api_key,
            settings=services.settings,
        )
        tools = ToolRunner(broker)
        session = ConversationSession(
            conversation_id=session_id,
            account_id=account_id,
            assistant_target=AssistantTarget(type=TargetType.EXPERT, id=package.manifest.agent_id),
        )
        turn = await build_turn_context(
            services,
            TurnContextRequest(
                session=session,
                user_input=user_input,
                run_id=run_id,
                phase_instance_id=assembled.plan.skill_id,
                expert=True,
                load_history=False,
            ),
        )
        request = PhaseExecutionRequest(
            run_id=run_id,
            phase_instance_id=assembled.plan.skill_id,
            phase_goal=assembled.plan.skill_id,
            system_prompt=assembled.plan.system_prompt,
            phase_input={"user_goal": user_input},
            context_summary=turn.history_summary,
            allowed_tools=tools.catalog_tool_names(),
            thinking_enabled=(
                services.settings.thinking_enabled and assembled.plan.thinking_preference != "off"
            ),
            thinking_budget=_resolve_thinking_budget(
                assembled.plan.thinking_preference, services.settings
            ),
            tool_message_max_chars=services.settings.agent_tool_message_max_chars,
            budget=build_agent_budget(services.settings, assembled.plan),
        )
        request = request.model_copy(
            update={
                "context_messages": turn.messages(system_prompt=build_phase_system_prompt(request))
            }
        )
        sink = _CollectingSink()
        thinking: list[str] = []
        workflow = build_workflow_definition(assembled.plan)
        if workflow is not None:
            outcome = await run_skill_workflow(
                llm=llm,
                tools=tools,
                events=sink,
                request=request,
                definition=workflow,
                display_text=None,
                display_thinking=thinking.append,
            )
        else:
            outcome = await run_agent_turn(
                llm=llm,
                tools=tools,
                events=sink,
                request=request,
                display_text=None,
                display_thinking=thinking.append,
            )
    finally:
        await broker.close()
    return PreviewResult(
        answer=_outcome_answer(outcome),
        outcome_type=outcome.outcome_type.value if outcome is not None else None,
        thinking="".join(thinking),
        events=[_serialize(event, seq) for seq, event in enumerate(sink.events, start=1)],
    )


async def run_tool_smoke(
    services: AppServices,
    package_id: uuid.UUID,
    *,
    tool_name: str,
    arguments: dict[str, object],
) -> ToolSmokeResult:
    """对草稿版本的工具执行一次真实调用（脚本 / MCP / 元工具均可）。"""
    assert services.skill_packages is not None
    assert services.registry is not None
    assert services.workspaces is not None
    package = await services.skill_packages.load_draft_package(package_id)
    assembler = AgentAssembler(
        registry=services.registry,
        workspaces=services.workspaces,
        mcp_manager=services.mcp_manager,
        script_executor=services.script_executor,
        settings=services.settings,
    )
    assembled = await assembler.assemble_from_package(
        package=package, account_id="debug", session_id=f"debug-{uuid.uuid4().hex}"
    )
    try:
        qualified = resolve_smoke_tool(assembled.broker, tool_name)
        call = ToolCallRequest(call_id="smoke", tool_name=qualified, arguments=arguments)
        results = await assembled.broker.execute([call])
    finally:
        await assembled.broker.close()
    return _smoke_result(results[0])


__all__ = ["resolve_smoke_tool", "run_draft_preview", "run_tool_smoke"]
