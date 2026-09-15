"""能力装配端口（P1#10）：harness 只依赖抽象，不识别 MCP / Script / 工作区具体实现。

单一动机：`AgentAssembler`（harness）不再直接实例化 `ToolBroker` / `WorkspaceManager`，
而是依赖 `CapabilityActivatorPort`——由组合根 / 适配层完成「工作区创建 + 工具代理激活」。
具体实现（ToolBroker / MCP / Script / Workspace）在 application 适配层装配。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.environment.tools.models import ToolCallRequest, ToolDescriptor, ToolResult
from app.harness.skill.assemble import AssemblyPlan
from app.llm.models import ChatToolSpec


class ToolBrokerPort(Protocol):
    """已激活工具代理端口：目录查询 + 分发 + 关闭（ToolBroker 满足）。"""

    def exposed_tools(self) -> list[ChatToolSpec]: ...
    def catalog_tool_names(self) -> list[str]: ...
    def get_descriptor(self, name: str) -> ToolDescriptor | None: ...
    async def execute(self, calls: list[ToolCallRequest]) -> list[ToolResult]: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class ActivatedCapability:
    """已激活的能力执行环境：工具代理 + 运行工作区根（纯运行时句柄）。"""

    # pragma: 简化 — 运行时句柄，不跨生命周期边界，无需 pydantic
    broker: ToolBrokerPort
    workspace_root: Path


class CapabilityActivatorPort(Protocol):
    """能力装配端口：把技能计划投影为「已激活工具代理 + 工作区」。

    harness 只依赖本端口；MCP / Script / ToolBroker / WorkspaceManager 的具体装配
    由 application 适配层（CapabilityActivator）完成。
    """

    async def activate(
        self,
        *,
        agent_id: str,
        skill_dir: Path,
        plan: AssemblyPlan,
        account_id: str,
        session_id: str,
        run_id: str,
    ) -> ActivatedCapability: ...


__all__ = ["ActivatedCapability", "CapabilityActivatorPort", "ToolBrokerPort"]
