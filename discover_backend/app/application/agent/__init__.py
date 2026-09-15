"""Agent 能力装配适配层（P1#10）：把 MCP / Script / ToolBroker / Workspace 具体装配收敛到一处。

harness 只依赖 `CapabilityActivatorPort`；本包提供生产适配器 `CapabilityActivator`，
由组合层（application.chat / bootstrap）注入 `AgentAssembler`。
"""

from app.application.agent.capability import CapabilityActivator

__all__ = ["CapabilityActivator"]
