"""H —— 驱动层（Harness）：用 LLM 与环境把一次任务跑完。

核心边界之一（`LLM + Harness + Environment = Agent System`）。本包持有
「Agent 如何被驱动」的全部知识：

```text
models / decision / progress      运行状态、结构化决策、无进展判定
policy / contracts                确定性约束与阶段完成判定
workflow / graph / react          阶段编排与阶段内 Bounded ReAct
execution/pipeline                工具运行时管线
service / turn / events           生命周期、并发回合句柄、事件发射
resolver / agent_runner           助手与技能解析、技能包装配后的执行入口
skill                             技能包（AGENT.md / SKILL.md）加载与装配
targets                           助手目标词汇（谁来应答）
checkpoint / wiring               快照协议与生产适配
```

边界约束：本层可依赖 `llm` 与 `environment`，但**不得**依赖 DDD 侧
（`domain` / `application` / `infrastructure` 的 CRUD 模块）与 `interfaces`。
"""

__all__: list[str] = []
