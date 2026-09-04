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
from app.runtime.graph import build_react_subgraph
from app.runtime.models import (
    BudgetLimits,
    BudgetState,
    PhaseExecutionOutcome,
    PhaseExecutionRequest,
)
from app.runtime.react.executor import (
    BoundedReActExecutor,
    EventSinkPort,
    LLMRunnerPort,
    ReactGraphState,
    ToolRunnerPort,
)
from app.runtime.resolver.assistant import AssistantResolver, ExplicitSelectionResolver
from app.runtime.resolver.skill import SkillResolutionContext, SkillResolver
from app.shared.errors.base import ConfigError


def build_agent_budget(settings: Settings) -> BudgetState:
    """从平台配置构建单阶段 ReAct 预算（CLAUDE.md §5 阈值一律进配置）。

    预算层级：平台硬上限 ≥ Agent 默认 ≥ Skill 默认 ≥ Phase 实际，下层只能收紧。
    """
    return BudgetState(
        limits=BudgetLimits(
            max_iterations=settings.agent_max_iterations,
            max_llm_calls=settings.agent_max_llm_calls,
            max_tool_calls=settings.agent_max_tool_calls,
            max_total_tokens=settings.agent_max_total_tokens,
            max_input_tokens=settings.agent_max_input_tokens,
            max_duration_seconds=settings.agent_max_duration_seconds,
            max_repair_attempts=settings.agent_max_repair_attempts,
            finalization_reserve_tokens=settings.agent_finalization_reserve_tokens,
        )
    )


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
