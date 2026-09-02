"""运行时动作词汇（runtime/execution）：模型做出的工具决策。

Action 复用 ToolBroker 的 ToolCallRequest（类型别名，不另造类型）——它是运行时
对「本轮要执行什么工具」的定义；未来 ReAct / SOP 状态机在此层演化，不触碰 Engine。
"""

from __future__ import annotations

from app.capabilities.tools.broker import ToolCallRequest

type Action = ToolCallRequest
