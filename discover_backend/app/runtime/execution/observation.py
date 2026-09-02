"""运行时观察词汇（runtime/execution）：工具执行后的产出。

Observation 复用 ToolBroker 的 ToolResult（类型别名）；单批执行聚合回写见
executor.ToolExecutionOutcome。
"""

from __future__ import annotations

from app.capabilities.tools.broker import ToolResult

type Observation = ToolResult
