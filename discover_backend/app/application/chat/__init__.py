"""对话用例（application/chat）：回合执行、上下文装配与并发回合协调。

对外接口是三个模块级入口：`run_turn.run_turn_events`（执行单轮）、
`turn_context.build_turn_context`（装配本轮上下文）、
`turn_registry.ActiveTurnRegistry`（同会话并发 409 与 stop 取消句柄）。
"""

__all__: list[str] = []
