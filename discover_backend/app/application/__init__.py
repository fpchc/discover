"""DDD 应用层：业务（CRUD）用例编排、跨边界 DTO 与服务容器。

本层同时是「业务驱动 Agent System」的接入点——chat 用例调用
`app/harness/` 驱动一次回合、经 `app/environment/` 取上下文与工具，
再落库到业务侧。反向不成立：`harness` / `llm` / `environment` 不认识
DDD 侧任何模块（由 `tests/unit/test_layering.py` 守卫）。

本包不承载协议细节（HTTP / SSE 在 `interfaces/`）。
"""

__all__: list[str] = []
