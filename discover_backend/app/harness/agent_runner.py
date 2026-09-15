"""Agent 对话执行入口：resolve/assemble/run 三件套，不依赖旧 Runtime 图节点。

正式内核已取代旧 Runtime：智能体解析、技能装配、单阶段 Bounded ReAct
执行在此统一归口。模块不保留版本前缀命名。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from app.config.settings import Settings
from app.environment.tools.models import ToolCallRequest, ToolResult
from app.harness.contracts.capability import CapabilityActivatorPort, ToolBrokerPort
from app.harness.execution.pipeline import ToolExecutionRequest
from app.harness.graph import build_react_subgraph
from app.harness.models import (
    BudgetLimits,
    BudgetState,
    PhaseExecutionOutcome,
    PhaseExecutionRequest,
    ProgressState,
)
from app.harness.react.executor import BoundedReActExecutor
from app.harness.react.ports import ActionGatewayPort, EventSinkPort, LLMRunnerPort
from app.harness.react.state import ReactGraphState
from app.harness.resolver.assistant import AssistantResolver, ExplicitSelectionResolver
from app.harness.resolver.skill import SkillResolutionContext, SkillResolver
from app.harness.skill.assemble import AssemblyPlan
from app.harness.skill.definition import AgentPackage
from app.harness.skill.registry import AgentRegistry
from app.harness.targets import AssistantTarget, TargetType
from app.harness.workflow.compiler import WorkflowRunner
from app.harness.workflow.definition import (
    PhaseDefinition,
    PhaseExecutorType,
    WorkflowDefinition,
)
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
        output_contract_refs=plan.workflow.output_contract_refs,
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
    """装配结果：已激活的工具代理（端口）+ 运行工作区根 + 装配计划。"""

    def __init__(self, *, broker: ToolBrokerPort, workspace_root: Path, plan: AssemblyPlan) -> None:
        self.broker = broker
        self.workspace_root = workspace_root
        self.plan = plan


class AgentAssembler:
    """Agent 解析与装配：选定智能体技能、装配计划、经端口激活能力。

    只依赖 `CapabilityActivatorPort`（能力装配端口）：MCP / Script / ToolBroker /
    Workspace 的具体装配在 application 适配层完成，harness 不识别具体实现（P1#10）。
    """

    def __init__(self, *, registry: AgentRegistry, capabilities: CapabilityActivatorPort) -> None:
        self._registry = registry
        self._capabilities = capabilities
        self._assistant_resolver: AssistantResolver = ExplicitSelectionResolver()
        self._skill_resolver = SkillResolver()

    async def resolve_and_assemble(
        self,
        *,
        assistant_target: AssistantTarget | None,
        account_id: str,
        session_id: str,
        run_id: str,
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
        plan = self._registry.assemble(target.id or "", skill_id)
        skill_dir = package.root / skill_id
        capability = await self._capabilities.activate(
            agent_id=target.id or "",
            skill_dir=skill_dir,
            plan=plan,
            account_id=account_id,
            session_id=session_id,
            run_id=run_id,
        )
        return AssemblyResult(
            broker=capability.broker, workspace_root=capability.workspace_root, plan=plan
        )

    async def assemble_from_package(
        self,
        *,
        package: AgentPackage,
        account_id: str,
        session_id: str,
        run_id: str | None = None,
    ) -> AssemblyResult:
        """从一个已加载的智能体包直接装配（草稿预览 / 调试路径）。

        与 resolve_and_assemble 的唯一差异：跳过目录解析，显式注入 package。
        """
        skill_ids = tuple(package.skills.keys())
        if not skill_ids:
            raise ConfigError("技能包无可用技能")
        context = SkillResolutionContext(
            skill_ids=skill_ids,
            default_skill=package.manifest.default_skill,
            explicit_skill=None,
        )
        skill_id = self._skill_resolver.resolve(context)
        if skill_id is None:
            raise ConfigError("无法解析技能")
        plan = self._registry.assemble_package(package, skill_id)
        skill_dir = package.root / skill_id
        capability = await self._capabilities.activate(
            agent_id=package.manifest.agent_id,
            skill_dir=skill_dir,
            plan=plan,
            account_id=account_id,
            session_id=session_id,
            run_id=run_id or uuid.uuid4().hex,
        )
        return AssemblyResult(
            broker=capability.broker, workspace_root=capability.workspace_root, plan=plan
        )


class _ToolGateRunner:
    """GateRunnerPort 生产适配：把 gate_<id> 脚本经 ActionGateway 统一执行（收口）。

    gate 脚本虽是内部可信校验器，仍走唯一工具执行入口（ActionGateway →
    ToolRuntime），避免 harness 层出现第二条 broker.execute 旁路。
    """

    def __init__(
        self,
        actions: ActionGatewayPort,
        *,
        run_id: str,
        phase_id: str,
        budget: BudgetState,
    ) -> None:
        self._actions = actions
        self._run_id = run_id
        self._phase_id = phase_id
        self._budget = budget

    def _find_gate_name(self, gate_id: str) -> str | None:
        suffix = f".script.gate_{gate_id}"
        for spec in self._actions.exposed_tools():
            if spec.function.name.endswith(suffix):
                return spec.function.name
        return None

    async def run_gate(self, *, gate_id: str, data: dict[str, object]) -> ToolResult:
        name = self._find_gate_name(gate_id)
        if name is None:
            return ToolResult(
                call_id=f"gate_{gate_id}",
                tool_name=f"gate_{gate_id}",
                ok=False,
                message=f"门禁脚本未装配：gate_{gate_id}",
                suggestion="在 SKILL.md gates 中为该门禁声明 validator 后再运行",
            )
        result = await self._actions.execute_batch(
            ToolExecutionRequest(
                run_id=self._run_id,
                phase_id=self._phase_id,
                iteration=0,
                calls=[ToolCallRequest(call_id=f"gate_{gate_id}", tool_name=name, arguments=data)],
                allowed_tools=[name],
                budget=self._budget,
                progress=ProgressState(),
            )
        )
        if not result.results:
            return ToolResult(
                call_id=f"gate_{gate_id}",
                tool_name=name,
                ok=False,
                message="门禁脚本执行返回为空",
                suggestion="检查门禁脚本输出",
            )
        return result.results[0]


async def run_skill_workflow(
    *,
    llm: LLMRunnerPort,
    actions: ActionGatewayPort,
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
            actions=actions,
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
        gate_runner=_ToolGateRunner(
            actions=actions,
            run_id=request.run_id,
            phase_id=request.phase_instance_id,
            budget=request.budget,
        ),
    )
    result = await runner.run(
        definition,
        run_id=request.run_id,
        phase_input=request.phase_input,
        budget=request.budget,
        allowed_tools=request.allowed_tools,
        context_summary=request.context_summary,
        context_messages=request.context_messages,
        system_prompt=request.system_prompt,
        thinking_enabled=request.thinking_enabled,
        thinking_budget=request.thinking_budget,
        tool_message_max_chars=request.tool_message_max_chars,
    )
    return result.final_outcome


async def run_agent_turn(
    *,
    llm: LLMRunnerPort,
    actions: ActionGatewayPort,
    events: EventSinkPort,
    request: PhaseExecutionRequest,
    display_text: Callable[[str], None] | None = None,
    display_thinking: Callable[[str], None] | None = None,
) -> PhaseExecutionOutcome | None:
    """跑单阶段 Agent 回合：构建 BoundedReActExecutor → 编译子图 → 执行 → 返回 outcome。"""
    executor = BoundedReActExecutor(
        llm=llm,
        actions=actions,
        events=events,
        display_text=display_text,
        display_thinking=display_thinking,
    )
    graph: CompiledStateGraph[ReactGraphState] = build_react_subgraph(executor)
    initial = ReactGraphState(request=request, budget=request.budget)
    final = await graph.ainvoke(initial)
    state = ReactGraphState.model_validate(final)
    return state.outcome
