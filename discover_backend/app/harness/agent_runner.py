"""Agent 对话执行入口：resolve/assemble/run 三件套，不依赖旧 Runtime 图节点。

正式内核已取代旧 Runtime：智能体解析、技能装配、单阶段 Bounded ReAct
执行在此统一归口。模块不保留版本前缀命名。
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph.state import CompiledStateGraph

from app.capabilities.mcp.manager import MCPManager
from app.capabilities.tools.broker import ToolBroker
from app.capabilities.tools.script_executor import ScriptExecutor
from app.config.settings import Settings
from app.domain.assistant.models import AssistantTarget, TargetType
from app.domain.skill.assemble import AssemblyPlan
from app.domain.skill.registry import AgentRegistry
from app.domain.workspace.service import Workspace, WorkspaceManager
from app.harness.graph import build_react_subgraph
from app.harness.models import (
    BudgetLimits,
    BudgetState,
    PhaseExecutionOutcome,
    PhaseExecutionRequest,
)
from app.harness.react.executor import (
    BoundedReActExecutor,
    EventSinkPort,
    LLMRunnerPort,
    ReactGraphState,
    ToolRunnerPort,
)
from app.harness.resolver.assistant import AssistantResolver, ExplicitSelectionResolver
from app.harness.resolver.skill import SkillResolutionContext, SkillResolver
from app.harness.workflow.compiler import WorkflowRunner
from app.harness.workflow.definition import PhaseDefinition, PhaseExecutorType, WorkflowDefinition
from app.harness.workflow.executors import (
    PhaseExecutorRegistry,
    ReactPhaseExecutor,
    RenderPhaseExecutor,
)
from app.shared.errors.base import ConfigError


def build_workflow_definition(plan: AssemblyPlan) -> WorkflowDefinition | None:
    """把技能清单中的 workflow 声明转换为运行时 WorkflowDefinition。

    领域层（SkillWorkflowDefinition）与运行时层（WorkflowDefinition）解耦；
    仅做字段映射，不含业务规则。
    """
    if plan.workflow is None:
        return None
    phases: list[PhaseDefinition] = []
    for phase in plan.workflow.phases:
        phases.append(
            PhaseDefinition(
                phase_id=phase.phase_id,
                executor_type=PhaseExecutorType(phase.executor),
                goal=phase.goal,
                allowed_tools=phase.allowed_tools,
                inherit_tools=phase.inherit_tools,
                input_bindings=phase.input_bindings,
                output_schema=phase.output_schema,
                fallback_phase=phase.fallback_phase,
            )
        )
    return WorkflowDefinition(
        workflow_id=plan.workflow.workflow_id,
        phases=phases,
    )


def build_agent_budget(settings: Settings, plan: AssemblyPlan | None = None) -> BudgetState:
    """从平台配置构建单阶段 ReAct 预算（CLAUDE.md §5 阈值一律进配置）。

    预算层级：平台硬上限 ≥ Agent 默认 ≥ Skill 默认 ≥ Phase 实际，下层只能收紧。
    智能体清单（AGENT.md）可声明 max_iterations / max_llm_calls / max_tool_calls /
    max_duration_seconds 收紧预算；未声明维度回落平台默认。
    """
    limits = BudgetLimits(
        max_iterations=settings.agent_max_iterations,
        max_llm_calls=settings.agent_max_llm_calls,
        max_tool_calls=settings.agent_max_tool_calls,
        max_total_tokens=settings.agent_max_total_tokens,
        max_input_tokens=settings.agent_max_input_tokens,
        max_duration_seconds=settings.agent_max_duration_seconds,
        max_repair_attempts=settings.agent_max_repair_attempts,
        finalization_reserve_tokens=settings.agent_finalization_reserve_tokens,
    )
    if plan is not None:
        overrides = {
            "max_iterations": plan.max_iterations,
            "max_llm_calls": plan.max_llm_calls,
            "max_tool_calls": plan.max_tool_calls,
            "max_duration_seconds": plan.max_duration_seconds,
        }
        limits = limits.model_copy(
            update={key: value for key, value in overrides.items() if value is not None}
        )
    return BudgetState(limits=limits)


class AssemblyResult:
    """装配结果：已激活的 broker + 工作区 + 装配计划。"""

    def __init__(self, *, broker: ToolBroker, workspace: Workspace, plan: AssemblyPlan) -> None:
        self.broker = broker
        self.workspace = workspace
        self.plan = plan


class AgentAssembler:
    """Agent 解析与装配：选定智能体技能、装配计划、激活工具代理。"""

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        workspaces: WorkspaceManager,
        mcp_manager: MCPManager | None,
        script_executor: ScriptExecutor | None,
        settings: Settings,
    ) -> None:
        self._registry = registry
        self._workspaces = workspaces
        self._mcp = mcp_manager
        self._script = script_executor
        self._settings = settings
        self._assistant_resolver: AssistantResolver = ExplicitSelectionResolver()
        self._skill_resolver = SkillResolver()

    async def resolve_and_assemble(
        self,
        *,
        assistant_target: AssistantTarget | None,
        account_id: str,
        session_id: str,
    ) -> AssemblyResult | None:
        target = self._assistant_resolver.resolve(assistant_target)
        if target is None or target.type == TargetType.GENERIC:
            return None
        agent = self._registry.index().agents.get(target.id or "")
        if agent is None:
            return None
        package = self._registry.get_agent(target.id or "")
        if package is None:
            return None
        skill_ids = tuple(package.skills.keys())
        if not skill_ids:
            return None
        context = SkillResolutionContext(
            skill_ids=skill_ids,
            default_skill=package.manifest.default_skill if package is not None else None,
            explicit_skill=None,
        )
        skill_id = self._skill_resolver.resolve(context)
        if skill_id is None:
            return None
        if self._mcp is None or self._script is None:
            raise ConfigError("MCP 管理器或脚本执行器未初始化，无法装配智能体")
        plan = self._registry.assemble(target.id or "", skill_id)
        skill_dir = package.root / skill_id
        workspace = await self._workspaces.create(target.id or "")
        broker = ToolBroker(
            settings=self._settings, mcp_manager=self._mcp, script_executor=self._script
        )
        activation = await broker.activate(
            plan=plan,
            skill_dir=skill_dir,
            workspace=workspace.root,
            session_id=session_id,
            account_id=account_id,
        )
        if not activation.ok:
            raise ConfigError(f"必需 MCP 依赖不可用：{', '.join(activation.failed_required)}")
        return AssemblyResult(broker=broker, workspace=workspace, plan=plan)


async def run_skill_workflow(
    *,
    llm: LLMRunnerPort,
    tools: ToolRunnerPort,
    events: EventSinkPort,
    request: PhaseExecutionRequest,
    definition: WorkflowDefinition,
    display_text: Callable[[str], None] | None = None,
    display_thinking: Callable[[str], None] | None = None,
) -> PhaseExecutionOutcome | None:
    """执行机器可读技能工作流。

    - react 阶段由 BoundedReAct 子图承载，阶段内只负责工具探索；
    - render 阶段由 RenderPhaseExecutor 确定性收尾，关闭普通工具；
    - 阶段间推进由 WorkflowRunner 的 fallback/完成条件决定，不依赖模型自觉
      调用 submit_final_answer / complete_phase。
    """
    react = ReactPhaseExecutor(
        BoundedReActExecutor(
            llm=llm,
            tools=tools,
            events=events,
            display_text=display_text,
            display_thinking=display_thinking,
        )
    )
    render = RenderPhaseExecutor(
        llm=llm,
        events=events,
        # render 正文由 _execute_turn 在拿到 outcome.answer 后统一推送，避免
        # 与 render 执行器内的流式展示重复（最终正文只发一次）。
        display_text=None,
        display_thinking=display_thinking,
    )
    registry = PhaseExecutorRegistry(
        {PhaseExecutorType.REACT: react, PhaseExecutorType.RENDER: render}
    )
    runner = WorkflowRunner(
        executors=registry,
        max_repair_attempts=request.budget.limits.max_repair_attempts,
    )
    result = await runner.run(
        definition,
        run_id=request.run_id,
        phase_input=request.phase_input,
        budget=request.budget,
        allowed_tools=request.allowed_tools,
        context_summary=request.context_summary,
        system_prompt=request.system_prompt,
        thinking_enabled=request.thinking_enabled,
        thinking_budget=request.thinking_budget,
        tool_message_max_chars=request.tool_message_max_chars,
    )
    return result.final_outcome


async def run_agent_turn(
    *,
    llm: LLMRunnerPort,
    tools: ToolRunnerPort,
    events: EventSinkPort,
    request: PhaseExecutionRequest,
    display_text: Callable[[str], None] | None = None,
    display_thinking: Callable[[str], None] | None = None,
) -> PhaseExecutionOutcome | None:
    """跑单阶段 Agent 回合：构建 BoundedReActExecutor → 编译子图 → 执行 → 返回 outcome。"""
    executor = BoundedReActExecutor(
        llm=llm,
        tools=tools,
        events=events,
        display_text=display_text,
        display_thinking=display_thinking,
    )
    graph: CompiledStateGraph[ReactGraphState] = build_react_subgraph(executor)
    initial = ReactGraphState(request=request, budget=request.budget)
    final = await graph.ainvoke(initial)
    state = ReactGraphState.model_validate(final)
    return state.outcome
