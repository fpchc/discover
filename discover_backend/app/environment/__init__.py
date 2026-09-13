"""E —— 环境层（Environment）：智能体可感知 / 可操作的世界。

核心边界之一（`LLM + Harness + Environment = Agent System`）。本包提供 agent
行动与感知的全部通道：

```text
tools/      工具端口词汇 + ToolBroker（三级目录 / 分发）+ 脚本宿主
mcp/        MCP 客户端与连接管理
context/    上下文平面（AgentContext 模型 / 来源端口 / 装配 / 投影 / 适配）
workspace/  智能体可写工作区（按 agent 键控）
storage/    字节存储后端（BaseStorage + local/s3）
```

边界约束：本层不依赖 `harness`，也不依赖 DDD 侧任何模块；下游只有
`llm`（端口词汇）/ `shared` / `config`。
"""

__all__: list[str] = []
