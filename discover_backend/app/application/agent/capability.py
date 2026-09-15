"""能力装配生产适配器（P1#10）。

单一动机：`AgentAssembler`（harness）不再直接实例化 `ToolBroker` / `WorkspaceManager`；
本适配器在 application 层完成「运行工作区创建 + 工具代理激活」，实现
`CapabilityActivatorPort`。MCP / Script / ToolBroker / Workspace 的装配细节只在此处可见。
"""

from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings
from app.environment.mcp.manager import MCPManager
from app.environment.tools.broker import ToolBroker
from app.environment.tools.script_executor import ScriptExecutor
from app.environment.workspace.service import WorkspaceManager
from app.harness.contracts.capability import ActivatedCapability
from app.harness.skill.assemble import AssemblyPlan
from app.shared.errors.base import ConfigError


class CapabilityActivator:
    """CapabilityActivatorPort 生产实现：创建运行工作区并激活工具代理。"""

    def __init__(
        self,
        *,
        settings: Settings,
        workspaces: WorkspaceManager,
        mcp_manager: MCPManager | None,
        script_executor: ScriptExecutor | None,
    ) -> None:
        self._settings = settings
        self._workspaces = workspaces
        self._mcp = mcp_manager
        self._script = script_executor

    async def activate(
        self,
        *,
        agent_id: str,
        skill_dir: Path,
        plan: AssemblyPlan,
        account_id: str,
        session_id: str,
        run_id: str,
    ) -> ActivatedCapability:
        if self._mcp is None or self._script is None:
            raise ConfigError("MCP 管理器或脚本执行器未初始化，无法装配智能体")
        workspace = await self._workspaces.create(
            agent_id,
            account_id=account_id,
            conversation_id=session_id,
            run_id=run_id,
        )
        broker = ToolBroker(
            settings=self._settings, mcp_manager=self._mcp, script_executor=self._script
        )
        activation = await broker.activate(
            plan=plan.tool_plan(),
            skill_dir=skill_dir,
            workspace=workspace.root,
            session_id=session_id,
            account_id=account_id,
        )
        if not activation.ok:
            raise ConfigError(f"必需 MCP 依赖不可用：{', '.join(activation.failed_required)}")
        return ActivatedCapability(broker=broker, workspace_root=workspace.root)


__all__ = ["CapabilityActivator"]
