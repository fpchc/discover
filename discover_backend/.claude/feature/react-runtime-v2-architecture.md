# Agent Runtime V2：Workflow + Bounded ReAct 架构方案

> **文档性质**：正式 Agent Runtime 目标架构与迁移方案  
> **创建日期**：2026-09-03  
> **状态**：设计方案，待确认后实施  
> **替代文档**：`react-optimization-proposal.md`、`react-agent-architecture.md`  
> **核心决策**：当前 ReAct Runtime 仅作为可行性 Demo；正式版本允许重构执行内核，不以兼容现有 Runtime 内部实现为首要目标。

---

## 1. 决策摘要

当前 Demo 已验证以下链路具备可行性：

- LLM 流式调用与工具调用；
- MCP、脚本工具统一暴露与执行；
- Agent/Skill Pack 动态加载与装配；
- LangGraph 节点编排；
- SSE 事件输出；
- 工作区、产物登记、对话落库；
- 用户取消与客户端断连处理。

正式架构不继续采用“在现有 `Runtime.run_turn()` 外包装 Guard”的方案，而是重构 `app/runtime`：

1. **Workflow Engine 拥有流程控制权**；
2. **ReAct 只是阶段内部的有界执行策略**；
3. **Policy 在 LLM 调用和工具执行前后实施确定性约束**；
4. **Contract/Gate 判断阶段和最终输出是否真正完成**；
5. **活跃 Run 的内存 RunState 是子图执行期权威状态，Checkpoint 只在阶段边界和副作用边界持久化**；
6. **Event 是 Runtime 对 HTTP/SSE、审计和观测的统一输出**；
7. **Conversation、Run、Step 分离建模**；
8. **平台不包含具体 Agent、Skill 或业务规则字面量**。

推荐范围是：

- 保留 `capabilities`、大部分 `domain` 和 `infrastructure`；
- 重构 Runtime、运行状态、执行拓扑、事件生命周期和 Runtime 组装方式；
- 渐进迁移 Skill Pack，不要求一次性重写所有业务资产。

---

## 2. 背景与问题定义

### 2.1 当前 Runtime 的定位

当前 Runtime 是验证性实现，主流程为：

```text
resolve_assistant
  → resolve_skill
  → assemble
  → agent
  ⇄ tool_node
  → finish
```

它适合验证端到端能力，但不应直接作为正式执行内核长期扩展。当前模型中，`agent ⇄ tool_node` 同时承担：

- 任务规划；
- 工具选择；
- 阶段推进；
- 数据质量判断；
- 是否继续；
- 是否完成；
- 是否重试或降级。

这会导致流程控制、概率推理和工具执行耦合在同一循环内。

### 2.2 正式架构需要解决的问题

1. 单次用户消息内的 ReAct 循环必须有硬边界；
2. 达到边界时必须生成可用的部分结果，而不是只中断；
3. 重复动作、重复结果和无进展循环必须可识别；
4. Token、时间、LLM 调用和工具调用需要统一预算；
5. 阶段是否完成不能仅由 LLM 自我声明；
6. 工具副作用、重试和恢复需要幂等策略；
7. 进程重启后应能恢复或明确终止 Run；
8. HTTP 连接生命周期不应成为执行状态的唯一宿主；
9. 多 Agent 扩展不能依赖另一个无限自由循环的 Supervisor；
10. 平台内核必须保持业务无关。

---

## 3. 目标与非目标

### 3.1 目标

- 建立 Run 驱动的正式 Agent Runtime；
- 使用 LangGraph 表达确定性流程和条件边；
- 支持单阶段和多阶段 Skill；
- 支持阶段内部 Bounded ReAct；
- 支持预算、取消、超时、重复和无进展控制；
- 复用现有 ToolBroker、MCP、脚本和产物能力；
- 支持结构、质量、证据三类 Contract；
- 支持 Checkpoint、恢复、审计和可观测性；
- 为未来父子 Run、多 Agent 协作预留稳定模型；
- 保持具体业务规则位于 Skill Pack。

### 3.2 非目标

- 不要求首期实现自由形式的多 Agent 自主协商；
- 不要求首期实现纯事件溯源；
- 不把模型原始思考文本作为流程控制依据；
- 不在平台中实现具体客户发现、授信或行业分析规则；
- 不承诺对当前 Runtime 内部状态和私有方法保持兼容；
- 不在首期引入新的任务队列框架。

### 3.3 核心范围与优先级

核心范围只保留两条 P0，两者共同决定“Workflow 控制、ReAct 执行”能否闭环。

#### P0-1：结构化决策通道

当前 LLM 流只产生 `TextChunk`、`ToolCallsChunk`、`UsageChunk` 以及用于展示 thinking/content 切换的 `PhaseSwitchChunk`。其中 `PhaseSwitchChunk` 不是 Workflow Phase，不能承载阶段控制。

首期不引入新的 Provider 结构化输出协议，统一复用现有 ToolCall 通道，通过 Runtime 注入的保留控制工具承载：

- `COMPLETE_PHASE`；
- `FINAL_ANSWER`；
- `NEED_CLARIFICATION`。

没有这条契约，`parse_decision` 节点没有确定性输入，“LLM 只有建议权、Engine 验证”无法成立。

#### P0-2：ReAct 与 Workflow 的接缝

核心不以“现有 SKILL.md 如何迁移”为前提，而是先固定 ReAct Executor 直接消费的 Phase 契约：

- Phase 输入；
- Phase 候选输出；
- 允许工具和预算；
- 完成提议如何进入 Contract；
- Contract 通过、修复、降级和失败如何回到 Workflow；
- Phase 输出如何传递给下一阶段。

Skill Pack 使用 Markdown frontmatter、YAML 或其他声明载体属于下游迁移问题，不阻塞核心契约实现。

#### P1：核心实现约束

1. **Checkpoint 粒度**：活跃 Run 以内存态为权威；只在阶段边界、Run 边界以及副作用工具执行前后落库，ReAct 子图普通内部节点不持久化。
2. **PARTIAL 事件化**：统一通过 `RunCompleted(status=PARTIAL, ...)` 表达，不依赖缺省字段或错误事件推断。
3. **无进展判定的近似性**：指纹无法证明语义相同，首期明确接受可观测、可配置的启发式误判和漏判。
4. **turn 语义迁移**：当前消息级 `turn` 拆为 conversation turn、phase iteration 与 step，测试、usage 和 `TurnRecord` 语义同步迁移。

Skill Pack 文件格式升级、多 Agent、历史事件完整回放等属于 P2 或后续演进。

## 4. 保留、重构与淘汰范围

### 4.1 建议保留

| 资产 | 处理方式 |
|---|---|
| LLM Client / Provider Registry / Stream Parser | 保留，补充调用级 usage 与取消契约 |
| MCP Manager | 保留，资源生命周期从会话 Runtime 中解耦 |
| ToolBroker | 保留为唯一工具分发出口 |
| ScriptExecutor | 保留，继续遵守 stdin/stdout 与工作区契约 |
| AgentRegistry / Skill Loader | 保留概念，扩展机器可读执行定义 |
| FileService / WorkspaceManager | 保留，改为按 Run/Agent 显式传递上下文 |
| Conversation/Auth | 保留，Conversation 与 Run 分离 |
| AgentEvent 基础模型 | 保留并扩展为完整运行事件 |
| Gate 脚本能力 | 保留并统一进入 Contract 体系 |

### 4.2 建议重构

| 当前部分 | 重构方向 |
|---|---|
| `app/runtime/engine.py` | 拆为 Run Engine、Workflow、ReAct、Policy、Finalize 职责 |
| `app/runtime/state.py` | 从单一 GraphState 演进为类型化 Run/Phase/Budget/Progress 状态 |
| `app/runtime/transition.py` | 构建 Workflow + Bounded ReAct 拓扑 |
| `AppServices.runtimes` | 移除“conversation_id → 有状态 Runtime”事实来源 |
| `_last_state` | 替换为持久化 Checkpoint |
| `_usage` 私有累计 | 纳入 Run Budget 和事件状态 |
| stop by conversation | 演进为 stop by run，保留会话级兼容入口 |
| HTTP 与图同生命周期 | 演进为 Run 执行与事件订阅解耦 |

### 4.3 建议淘汰

- 在完整 `run_turn()` 外执行 Pre/Post Guard；
- 跨用户消息累积推理轮次并据此永久阻断会话；
- 根据 LangGraph 节点名或 `active_skill` 判断状态震荡；
- 用自由文本 `suggested_action` 控制 Engine；
- 平台内的具体业务 Contract 类；
- 第二个外层 `while True` 包装已经有循环的 LangGraph；
- 将内存 Runtime 对象作为会话执行状态的唯一事实来源。

---

## 5. 核心架构原则

### 5.1 ReAct 是执行策略，不是顶层控制器

Workflow 决定“当前做哪个阶段”，ReAct 只决定“当前阶段内下一步尝试什么动作”。

### 5.2 Engine 拥有控制权，LLM 只有建议权

LLM 可以提议：

- 调用工具；
- 完成当前阶段；
- 生成最终输出。

Engine 必须验证：

- 当前提议是否属于允许的决策类型；
- 工具是否在当前阶段白名单内；
- 是否有剩余预算；
- 是否属于重复无进展动作；
- Contract 是否允许阶段完成；
- 是否应重试、降级、部分完成或终止。

### 5.3 安全约束必须进入图内控制点

Guard/Policy 的检查点必须位于：

1. LLM 调用前；
2. LLM 决策解析后；
3. 工具执行前；
4. 工具执行后；
5. Contract 检查后；
6. 最终输出前。

不得只包装整个图执行入口。

### 5.4 状态与事件是类型化契约

跨生命周期的 Run、Step、Action、Observation、Contract、Event、Outcome 均使用 Pydantic `BaseModel`。运行时句柄通过依赖注入传递，不写入持久化状态。

### 5.5 业务规则留在 Skill Pack

平台只认识通用的：

- Workflow Definition；
- Phase Definition；
- Policy Definition；
- Contract Definition；
- Tool Descriptor；
- Run State。

平台不认识 `client-finder`、具体企业字段或具体行业评分规则。

---

## 6. 总体架构

```text
┌─────────────────────────────────────────────────────┐
│ Interfaces                                          │
│ HTTP / SSE：创建 Run、订阅事件、查询状态、取消 Run │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│ AgentRunService                                     │
│ create / execute / resume / cancel / query          │
└──────────────┬──────────────────┬───────────────────┘
               │                  │
┌──────────────▼─────────────┐    │    ┌────────────────────────┐
│ Workflow Runtime           │    │    │ RunStore / EventStore  │
│                            │    └───►│ snapshot + audit log   │
│ initialize                 │         └────────────────────────┘
│ resolve / compile          │
│ phase loop                 │
│ contract                   │
│ finalize                   │
└──────────────┬─────────────┘
               │
       ┌───────▼────────┐
       │ ReAct Executor │
       │ bounded loop   │
       └───────┬────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│ Policy Engine                                      │
│ budget / action / progress / retry / side-effect  │
└──────────────┬──────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────┐
│ Tool Runtime                                       │
│ preflight → broker → normalize → artifact → audit │
└──────────────┬──────────────────────────────────────┘
               │
      ┌────────┴───────────┐
      │ MCP / Script /     │
      │ Internal Capability│
      └────────────────────┘
```

---

## 7. 执行模型

正式架构区分四个标识：

| 标识 | 含义 |
|---|---|
| `conversation_id` | 用户对话容器 |
| `message_id` | 一条用户或助手消息 |
| `run_id` | 一次 Agent 执行实例 |
| `step_id` | 一次 LLM、Tool、Contract 或 Finalize 步骤 |

### 7.1 Run 生命周期

```text
CREATED
  → RUNNING
  ├── WAITING_INPUT
  │     └── RUNNING
  → FINALIZING
  → SUCCEEDED | PARTIAL | FAILED | CANCELLED
```

其中：

- `WAITING_INPUT` 是可恢复的暂停状态，由 `NEED_CLARIFICATION` 提议并经 Engine 验证后进入；
- 后续用户输入显式关联原 `run_id` 后恢复当前 Phase；
- 恢复不会自动清零已消耗预算，可由 Phase Policy 提供有限的 clarification allowance；
- `PARTIAL` 是正常完成类终态，不等同于 `FAILED`；
- `RECOVERING`、`CANCEL_REQUESTED` 可作为内部过渡状态，但不改变最终终态集合。

### 7.2 终止原因

终态与原因分离，建议至少支持：

- `completed`；
- `iteration_limit`；
- `token_budget`；
- `time_budget`；
- `tool_budget`；
- `no_progress`；
- `contract_failed`；
- `required_tool_unavailable`；
- `user_cancelled`；
- `client_disconnected`；
- `runtime_shutdown`；
- `internal_error`。

`PARTIAL` 表示有可交付结果但未完成全部目标；原因说明为何部分完成。

---

## 8. 状态模型

不继续向一个巨型 GraphState 无限制追加字段。正式状态按职责组合。

### 8.1 RunState

RunState 负责一次执行的权威快照，建议包含：

- 身份：run、conversation、message、account；
- 目标：agent、skill、用户目标；
- Workflow：阶段清单、当前阶段、阶段状态；
- 上下文：必要对话引用、阶段摘要；
- 输出：阶段输出、最终草稿、产物；
- 控制：BudgetState、ProgressState、CancellationState；
- 审计：当前 step、版本、创建/更新时间；
- 终止：状态、原因、partial 标记、错误分类。

### 8.2 PhaseState

每个阶段独立记录：

- `phase_id`；
- `status`；
- `attempt`；
- `iteration`；
- `input`；
- `output`；
- `contract_results`；
- `started_at` / `completed_at`；
- `degraded_sources`；
- `repair_attempts`。

### 8.3 BudgetState

预算至少覆盖：

- 最大 ReAct 迭代数；
- 最大 LLM 调用数；
- 最大工具调用数；
- 最大总 Token；
- 最大输入 Token；
- 最大执行时长；
- 最大 Contract 修复次数；
- 最终输出保留 Token。

预算层级：

```text
平台硬上限
  ≥ Agent 默认预算
    ≥ Skill 默认预算
      ≥ Phase 实际预算
```

下层只能收紧，不能突破平台硬上限。

### 8.4 ActionRecord / ObservationRecord

ActionRecord 至少记录：

- action/step ID；
- tool name；
- 类型化 arguments；
- 规范化 arguments fingerprint；
- 状态、重试关系、幂等键；
- 起止时间。

ObservationRecord 至少记录：

- tool result 状态；
- 内容摘要或 Blob 引用；
- observation fingerprint；
- 错误分类；
- 产物；
- 是否截断；
- progress delta。

### 8.5 ProgressState

记录：

- `progress_version`；
- 连续无进展步数；
- 最近 Action/Observation 指纹对；
- 新增证据数；
- 新增产物数；
- Gate/Contract 状态变化；
- 最近 Contract 得分或失败项变化。

---

## 9. Workflow 模型

### 9.1 单阶段 Skill

简单 Skill 可编译为：

```text
initialize
  → react_phase
  → output_contract
  → finalize
```

### 9.2 多阶段 Skill

复杂 Skill 可声明为：

```text
initialize
  → phase_1
  → phase_1_contract
  → phase_2
  → phase_2_contract
  → output_contract
  → finalize
```

阶段可采用不同执行器：

- `react`：有界 ReAct；
- `script`：确定性脚本；
- `tool`：固定工具调用；
- `contract`：校验；
- `transform`：类型化状态转换；
- `render`：产物生成。

具体阶段名称和业务含义由 Skill Pack 声明，平台通过通用执行器注册表解释。

### 9.3 阶段完成原则

LLM 只能通过保留控制工具“提议阶段完成”，Engine 必须执行：

```text
COMPLETE_PHASE(candidate_output)
  → Phase Contract
  → Policy Decision
  ├── PASS    → 固化 PhaseOutput → 映射下一阶段输入
  ├── REPAIR  → 将 failures 回注当前 Phase → 有界重试
  ├── DEGRADE → 固化带 limitations 的 PhaseOutput → 下一阶段
  ├── PARTIAL → 进入 Run Finalize
  └── FAIL    → Run Failed
```

不得通过自然语言中的“已完成”直接推进 Workflow。

### 9.4 PhaseExecutionContract：ReAct 与 Workflow 的核心接缝

这是 V2 核心必须先固定的契约，独立于 Skill Pack 最终采用何种文件格式。

#### PhaseExecutionRequest

Workflow 调用 ReAct Executor 时提供：

- `run_id`、`phase_instance_id`、`attempt`；
- 当前阶段目标和类型化 Phase Input；
- 上游 PhaseOutput 的只读引用或显式字段绑定；
- 当前上下文摘要；
- allowed tools；
- BudgetState；
- Contract 引用；
- 已消耗 usage、最近 Observation 和恢复信息。

不得把整个可变 RunState 无边界地交给 ReAct Executor。ReAct 只能更新当前 Phase 的候选输出、Action/Observation、usage 和 progress。

#### PhaseExecutionOutcome

ReAct Executor 返回以下一种结构化结果：

- `CANDIDATE_COMPLETED`：由 `COMPLETE_PHASE` 产生，携带 candidate output；
- `FINAL_PROPOSED`：由 `FINAL_ANSWER` 产生；
- `INPUT_REQUIRED`：由 `NEED_CLARIFICATION` 产生；
- `PARTIAL_BUDGET`：预算软边界；
- `PARTIAL_NO_PROGRESS`：无进展边界；
- `FAILED`：不可恢复的解析、工具或策略失败。

Outcome 同时携带：

- candidate output 或 answer；
- usage/budget snapshot；
- Action/Observation 引用；
- artifacts；
- limitations；
- reason code。

#### PhaseOutput

通过 Contract 后生成不可变、带版本的 PhaseOutput：

- `phase_id`、`schema_version`；
- 类型化 data；
- evidence/artifact references；
- limitations/degraded sources；
- ContractResult；
- produced_at。

下一阶段只能通过 Workflow 中声明的 input bindings 读取上游 PhaseOutput，不直接读写其他阶段内部状态。

#### 闭环规则

1. Workflow 构造 PhaseExecutionRequest；
2. ReAct 在当前 Phase 内执行；
3. 控制工具产生 PhaseExecutionOutcome；
4. Workflow 执行 Contract/Policy；
5. 通过后固化 PhaseOutput 并推进；
6. 修复时只回到当前 Phase，且消耗 repair budget；
7. clarification 时持久化阶段边界快照并进入 `WAITING_INPUT`；
8. ReAct 不得自行切换 Phase 或直接修改 Run 终态。

## 10. Bounded ReAct 子图

推荐子图：

```text
react_prepare
  → check_budget
  → call_llm
  → parse_decision
  → validate_decision
      ├── action → preflight_action
      ├── phase_complete → phase_contract
      └── final → output_contract
  → execute_tool
  → normalize_observation
  → evaluate_progress
      ├── continue
      ├── retry
      ├── degrade
      ├── finalize_partial
      └── terminate
```

### 10.1 结构化决策通道（P0-1）

首期复用现有 ToolCall 通道，不新增 Provider 专属的 JSON mode 或另一套结构化输出解析器。Runtime 在每次专家 ReAct 调用时，将普通业务工具和保留控制工具共同注入 `ChatRequest.tools`。

#### 保留控制工具

建议固定三个平台保留名称：

| 控制工具 | 产生的决策 | 核心参数 |
|---|---|---|
| `complete_phase` | `COMPLETE_PHASE` | `output`、`summary`、`evidence_refs`、`limitations` |
| `submit_final_answer` | `FINAL_ANSWER` | `answer`、`structured_output`、`artifact_ids`、`limitations` |
| `request_clarification` | `NEED_CLARIFICATION` | `question`、`missing_fields`、`reason` |

约束：

- 名称属于 Runtime 保留命名空间，Skill/MCP/脚本不得注册同名工具；
- 控制工具由 Runtime 生成 Pydantic 参数 schema；
- 控制工具不会进入 ToolBroker，也不产生 ToolCallStarted/Completed；
- 当前 `phase_id` 由 Engine 绑定，模型不能通过参数切换阶段；
- `PhaseSwitchChunk` 仅表示模型 thinking/content 展示切换，与 Workflow Phase 无关。

#### ToolCallsChunk 到 AgentDecision 的映射

流结束后，`parse_decision` 按以下确定性规则归一：

1. 只有普通工具调用：`CALL_TOOLS`，允许同批多个调用；
2. 恰好一个控制工具且没有普通工具：映射为对应控制决策；
3. 控制工具与普通工具混用：`INVALID_DECISION`；
4. 同时出现多个控制工具：`INVALID_DECISION`；
5. 只有 TextChunk、没有 ToolCall：在专家 Workflow 中视为非权威 draft，触发一次有界格式修复；修复仍失败则按 Policy 终止或部分完成；
6. 通用聊天不进入该协议，仍可直接以文本完成。

TextChunk 可以作为面向用户的过程文本或控制工具参数的草稿，但不能单独推进 Phase。

#### 决策验证

Engine 在接受控制决策前继续验证：

- `COMPLETE_PHASE` 仅能完成当前 Phase，candidate output 必须通过 Phase 输入/输出 schema 和 Contract；
- `FINAL_ANSWER` 仅在 Workflow 允许 Finalize 的位置生效，否则拒绝并有界修复；
- `NEED_CLARIFICATION` 必须说明缺失输入，且 Phase Policy 允许暂停；通过后发出 `RunInputRequested` 并进入 `WAITING_INPUT`；
- 解析失败和格式修复均计入 LLM、Token 和 repair budget。

该协议是首期 P0。未来即使增加 Provider 原生结构化输出，也必须先归一为同一个 AgentDecision，不改变 Workflow/ReAct 接缝。

### 10.2 Soft Limit 与 Hard Limit

- Soft Limit：停止工具探索，进入部分总结；
- Hard Limit：禁止任何新 LLM/工具调用，使用确定性终止输出。

达到上限后不能只追加一条“请总结”的 system message然后直接结束；必须显式进入 Finalize 节点。

---

## 11. Policy Engine

原四层 Guard 统一升级为 Policy 系统。

### 11.1 Policy 分类

#### Run Policy

- 总 Token；
- 总时长；
- 总 LLM/工具调用；
- 账号配额；
- 用户取消；
- 系统关闭。

#### Phase Policy

- 当前阶段迭代数；
- 阶段允许工具；
- 阶段时间预算；
- 阶段修复次数；
- 阶段降级策略。

#### Action Policy

- 工具是否存在且可用；
- 参数 schema 是否通过；
- 是否越权使用其他阶段工具；
- 是否为重复无进展动作；
- 是否允许重试；
- 是否满足副作用和幂等要求。

#### Observation Policy

- 返回是否为空；
- 是否重复相同结果；
- 是否重复相同错误；
- 是否产生新证据或产物；
- 是否应切换数据源或进入降级。

### 11.2 PolicyDecision

Policy 结果采用结构化枚举，不使用自由文本控制流程：

- `ALLOW`；
- `RETRY`；
- `SKIP`；
- `DEGRADE`；
- `FINALIZE_PARTIAL`；
- `TERMINATE`；
- `FAIL`。

结果同时携带：

- reason code；
- 面向用户的可展示说明；
- retry delay/attempt；
- fallback phase；
- budget snapshot；
- 是否可恢复。

---

## 12. 无进展与循环检测

### 12.1 不检测节点名称循环

以下序列在 ReAct 中是正常拓扑：

```text
agent → tool → agent → tool
```

因此不得根据 LangGraph 节点名判断震荡。

### 12.2 Action Fingerprint

Action 指纹由以下内容生成：

- 工具限定名；
- 参数经过稳定排序和规范化后的 JSON；
- 工具描述中声明的忽略字段；
- 当前阶段 ID。

动态时间戳、追踪 ID 等非语义字段可由 Tool Descriptor 声明为不参与指纹。

### 12.3 Observation Fingerprint

Observation 指纹至少包含：

- 成功/失败状态；
- 归一化内容摘要；
- 错误分类；
- 产物摘要；
- 数据版本或来源标识。

### 12.4 判定条件

推荐判定“无进展循环”，而不是单纯判定重复：

```text
Action 指纹重复
+ Observation 指纹重复
+ 没有新增证据
+ 没有新增产物
+ Contract 没有改善
+ 连续达到阈值
= no_progress
```

合法重试应满足：

- 上次为可重试错误；
- 未超过 max attempts；
- 符合退避策略；
- Tool Descriptor 允许重试。

### 12.5 首期近似性声明（P1）

Action/Observation fingerprint 只能判断规范化后的结构是否相同，不能证明业务语义相同：

- 参数改写、同义查询可能导致语义重复但指纹不同，形成漏判；
- 相同查询用于轮询动态数据时可能是合法行为，形成误判；
- 内容摘要、截断和顺序变化可能影响 Observation 指纹；
- “是否新增证据”依赖 Skill/Tool 提供的有限信号，不是完整语义理解。

首期明确接受这项 P1 近似，不引入额外 LLM 做语义相似度裁决，避免检测器本身增加成本和不确定性。缓解措施：

- 首期优先使用严格规范化后的精确指纹；
- 同时要求连续无 progress delta，不能只凭 Action 相同终止；
- Tool Descriptor 可声明 polling、retry 或 fingerprint ignore fields；
- 阈值配置化并采用保守默认值；
- 命中时发出可观测的 `ProgressStalled`/Policy 事件；
- 默认进入 `FINALIZE_PARTIAL`，而不是把近似命中当作内部错误；
- Golden Case 持续收集误杀和漏过样本，后续再决定是否增加领域 progress signal。

## 13. 预算与最终输出保留

### 13.1 预算不仅是 Token

正式 Resource Budget 包括：

- Token；
- LLM 调用次数；
- 工具调用次数；
- 墙钟时间；
- Contract 修复次数；
- 可选的货币成本。

货币成本只有在 Provider Registry 具备可版本化价格信息时才启用；否则命名为 Token/Resource Budget，不误称为精确 Cost。

### 13.2 Finalization Reserve

总预算分为：

```text
work budget + finalization reserve
```

工作预算接近耗尽时：

1. 禁止新工具调用；
2. 进入 `FINALIZING`；
3. 使用保留预算生成部分结论；
4. 输出明确的数据缺失、降级和终止原因。

若保留预算也不可用，则由确定性模板生成终止说明，不再调用 LLM。

---

## 14. Contract 与现有 Gate 的统一

### 14.1 统一模型

```text
ContractDefinition
  → ContractExecutor
  → ContractResult
  → Workflow Transition
```

现有 Gate 脚本作为 ContractExecutor 的一种实现，不再建设平行体系。

### 14.2 Contract 类型

#### Structural Contract

- JSON Schema；
- 必填字段；
- 类型和格式；
- 产物存在性；
- 渲染结构完整性。

#### Quality Contract

- 数量、覆盖率、置信度；
- 数据源数量；
- 评分完整性；
- Skill 自定义质量指标。

#### Evidence Contract

- 关键结论是否关联证据；
- 来源是否记录；
- 推断内容是否标记；
- 冲突证据是否披露；
- 降级来源是否说明。

### 14.3 ContractResult

至少包含：

- `PASS` / `WARN` / `FAIL`；
- failures；
- warnings；
- score；
- evidence summary；
- remediation；
- retryable；
- fallback。

### 14.4 有界修复

Contract 失败后的路径必须配置：

- retry current phase；
- return to phase；
- degrade to warning；
- finalize partial；
- fail run。

所有修复受 `max_repair_attempts` 和独立 repair budget 约束，Contract 不得制造无限返工循环。

---

## 15. Tool Runtime

现有 ToolBroker 继续作为唯一分发出口，ToolExecutor 演进为完整管线：

```text
ToolRequest
  → resolve descriptor
  → validate schema
  → authorize for phase
  → check budget
  → check repetition/no-progress
  → check side effect
  → attach idempotency key
  → execute through broker
  → normalize observation
  → register artifacts
  → evaluate progress
  → checkpoint
  → emit events
```

### 15.1 Tool Descriptor 扩展

建议描述：

- tool ID、namespace、输入 schema；
- timeout；
- side-effect type；
- idempotent；
- retryable；
- max attempts；
- result truncation；
- fingerprint ignore fields；
- 可用阶段或 capability tags。

### 15.2 副作用与恢复

工具至少区分：

- read-only；
- workspace-write；
- database-write；
- external-write；
- irreversible。

执行副作用工具前保存 Planned Action Checkpoint，并生成幂等键。恢复时：

- 幂等工具可安全重试；
- 可查询状态的工具先查询结果；
- 无法确认的不可逆工具不得盲目重放，应将 Run 标记为需要明确失败或人工确认的状态。

---

## 16. Checkpoint 与并发控制

### 16.1 权威状态与持久化边界（P1）

首期采用“执行期内存权威、边界持久化”的模型：

- 一个活跃 Run 由单一执行者持有内存 RunState；
- Bounded ReAct 子图普通内部节点不逐节点落库；
- 持久化 Snapshot 用于阶段级恢复，不作为每个子图节点的同步镜像；
- durable audit 只记录 Run/Phase 边界和副作用 Action 边界；
- TextDelta、ThinkingDelta、普通内部路由等高频事件不作为首期恢复依据。

因此首期不是纯事件溯源，也不承诺从任意 ReAct 内部节点精确续跑。进程在普通只读探索期间崩溃时，从最近 Phase 边界重新执行该 Phase；已消耗但未落库的只读 LLM/Tool 步骤允许重放。

### 16.2 Checkpoint 粒度

只在以下边界持久化：

1. Run 创建/开始；
2. Phase 进入；
3. Phase 完成、降级、部分完成或失败；
4. 进入 `WAITING_INPUT` 与恢复；
5. 副作用工具执行前：保存 Planned Action、幂等键和参数指纹；
6. 副作用工具执行后：保存 Observation、外部结果标识和状态；
7. Run Finalize 与所有终态；
8. 显式取消或 Runtime shutdown 的安全边界。

以下节点首期不单独持久化：

- 每次 LLM 调用前后；
- `parse_decision`；
- 普通只读工具调用前后；
- `evaluate_progress`；
- ReAct 子图内部条件边。

这样避免将 §10 的八节点子图放大为高频数据库写入，同时明确接受“崩溃后从 Phase 边界重放只读工作”的代价。

### 16.3 副作用恢复

- 幂等副作用工具可使用原幂等键重试；
- 可查询外部状态的工具先查询已执行结果；
- 无法确认结果的不可逆工具不得盲目重放，Run 进入明确失败或待处理状态；
- 普通只读工具无需执行前 Checkpoint，阶段重启时允许再次调用。

### 16.4 执行租约

同一 Run 同时只能有一个执行者。建议通过 PostgreSQL 状态版本与 Redis 执行租约控制：

- owner ID；
- lease expiration；
- heartbeat；
- optimistic version；
- cancel flag。

租约保证执行者唯一；内存 RunState 保证活跃执行期权威；阶段/副作用 Checkpoint 保证有限恢复。不得依赖进程内全局可变字典实现跨进程唯一执行。

## 17. Event 模型与接口适配

Runtime 对外统一发出类型化事件，HTTP/SSE 只负责映射。

建议事件：

- `RunStarted`；
- `PhaseStarted`；
- `LLMCallStarted`；
- `LLMUsageUpdated`；
- `ActionProposed`；
- `ActionRejected`；
- `ToolCallStarted`；
- `ToolCallCompleted`；
- `ProgressUpdated` / `ProgressStalled`；
- `ContractChecked`；
- `PhaseCompleted`；
- `RunInputRequested`；
- `RunDegraded`；
- `RunFinalizing`；
- `RunCompleted`；
- `RunCancelled`；
- `RunFailed`。

每个事件至少包含：

- run ID；
- step ID；
- 活跃执行期单调递增 sequence；
- timestamp；
- phase ID；
- 可展示信息与内部 reason code 的分离字段。

高频运行事件用于实时观测，不等同于 Checkpoint；首期不保证断线后重放全部 Text/Thinking/内部步骤事件。

### 17.1 PARTIAL 的终态事件契约（P1）

不新增语义模糊的 `RunPartially`，统一由 `RunCompleted` 表达正常完成类终态：

```text
RunCompleted
  status: SUCCEEDED | PARTIAL
  termination_reason
  final_output
  completed_phases
  unfinished_phases
  limitations
  degraded_sources
  budget_snapshot
```

约束：

- `PARTIAL` 不是 `RunFailed`；
- budget/no-progress/数据受限/非阻断 Contract 均可形成 PARTIAL；
- `RunFailed` 只表达无可交付结果或不可恢复错误；
- `RunCancelled` 单独表达用户或系统取消；
- HTTP blocking 和 SSE `message_end` 必须映射相同的 status、reason 和 limitations；
- Conversation `TurnRecord` 的状态由 Run 终态显式映射，不能根据是否收到 ErrorEvent 推断。

### 17.2 SSE 结束契约

所有终态必须发出且持久化明确结束事件：

- 成功/部分完成：`RunCompleted`；
- 失败：`RunFailed`；
- 取消：`RunCancelled`。

`WAITING_INPUT` 发出 `RunInputRequested`，它是暂停事件而不是结束事件。HTTP 层不得通过“队列自然为空”猜测 Run 是否正常结束。

### 17.3 HTTP 断连

正式架构默认将“客户端断开订阅”和“取消 Run”分离：

- SSE 断开仅停止当前订阅；
- 显式 stop/cancel 才请求取消 Run；
- 重连时首期读取最新 Run Snapshot 并订阅后续事件，不保证回放已丢失的高频事件；
- 若产品要求断连即取消，可作为接口策略配置，而不是 Runtime 固有语义。

## 18. 对话记忆、执行轨迹与 LLM Context

### 18.1 turn、iteration、step 与 phase 的映射（P1）

当前 `GraphState.turn` 表示“单条用户消息内的推理轮次”，每条消息开始时重置。V2 不继续使用含义模糊的单一 `turn`：

| V2 术语 | 含义 | 重置规则 |
|---|---|---|
| conversation turn | 一条用户输入及其对应 Run/回答，属于对话落库语义 | 每条用户消息新增 |
| run | 一次目标执行；通常由一条用户消息创建，clarification 可暂停并恢复同一 Run | Run 终止后结束 |
| phase | Workflow 中的确定性阶段 | 按 Workflow 推进 |
| phase iteration | 当前 Phase 内一次 ReAct 决策循环 | 进入新 Phase 时重置 |
| step | 一次 LLM、单个 Tool、Contract 或 Finalize 执行单元 | Run 内单调新增 |

迁移规则：

- 当前 `turn` 迁移为 `PhaseState.iteration`，不跨 Phase 累积；
- 多工具批次共享 decision step，但每个 ToolCall 拥有独立 tool step/action ID；
- 当前 `DoneEvent.turns` 弃用，替换为 `react_iterations`、`llm_calls`、`tool_calls` 等明确指标；
- `TurnRecord` 继续表示 conversation turn，不改成 Runtime step；
- `TurnRecord.status`、usage 和 duration 从对应 Run 终态聚合；
- 现有测试中“turn 上限”改写为“单 Phase iteration 上限”；
- clarification 恢复同一 Phase，不自动清零已消耗 iteration/usage。

### 18.2 Conversation Memory

用户可见内容：

- user message；
- assistant answer；
- attachment/artifact reference。

### 18.3 Run Trace

执行审计：

- action；
- observation；
- contract；
- budget；
- retry；
- degradation；
- termination。

首期 durable trace 服从 §16 的边界持久化策略；完整高频事件回放属于后续能力。

### 18.4 LLM Context

每次调用临时组装：

- 系统约束；
- Agent/Skill 指令；
- 当前阶段目标；
- 必要对话历史；
- 阶段摘要；
- 最近 Action/Observation；
- 当前可用工具；
- 三个 Runtime 保留控制工具。

LLM Context 是派生数据，不作为权威状态。模型原始思考文本不得参与流程控制；如产品需要展示，可流式透传或保存受控摘要，但不作为 Contract 或阶段完成依据。

## 19. Skill Pack 演进（P2，下游事项）

Skill Pack 文件格式不属于两条核心 P0。Runtime V2 首先固定 §9.4 的 PhaseExecutionContract 与 §10.1 的 AgentDecision；现有 Skill 可以通过临时 Adapter 或测试定义生成 PhaseExecutionRequest。

是否将当前 Markdown frontmatter 拆为 `agent.yaml` / `skill.yaml`，在核心内核验证后再单独决策。候选目标格式为：

```text
agents/{agent}/
├── agent.yaml
├── AGENT.md
└── {skill}/
    ├── skill.yaml
    ├── SKILL.md
    ├── schemas/
    ├── contracts/
    ├── scripts/
    ├── references/
    └── templates/
```

候选职责：

- `agent.yaml`：ID、版本、默认 Skill、模型偏好和 Agent 默认策略；
- `skill.yaml`：输入输出 schema、Workflow、工具依赖、阶段预算、Contract 和 fallback；
- `AGENT.md` / `SKILL.md`：角色、业务方法、决策原则和 LLM 指令。

该格式不是 V2 Core 的前置条件。迁移期 loader 可继续读取现有 frontmatter，由 Adapter 编译成同一个 Workflow/Phase 定义；只有在至少一个 V2 Skill 验证完成后，才决定是否引入新文件规范并移除兼容分支。

## 20. 多 Agent 演进

首期不实现自由 Supervisor 循环。未来多 Agent 采用父子 Run：

```text
Parent Run
  → create Child Run with objective/input/budget/contract
  → await child terminal event
  → validate child output
  → merge or fallback
```

Child Run 具有：

- 独立 run ID；
- 独立预算；
- 明确输入输出 Contract；
- parent run ID；
- 取消传播；
- 独立事件和 Checkpoint。

Coordinator 只能在 Workflow 允许的位置创建子 Run，不能无限自由委派。父 Run 对子 Run 数量、总预算和最大深度设置硬限制。

---

## 21. 建议模块结构

目标结构示意：

```text
app/runtime/
├── engine.py                 # Run 执行入口，只做编排
├── models.py                 # Run/Phase/Budget/Progress/Termination
├── graph.py                  # LangGraph 构建与条件边
├── service.py                # create/resume/cancel/query Run
├── workflow/
│   ├── definition.py         # Workflow/Phase 定义
│   ├── compiler.py           # Skill Definition → 可执行图
│   └── executors.py          # 通用阶段执行器注册表
├── react/
│   ├── decision.py           # 结构化决策模型与解析
│   ├── executor.py           # Bounded ReAct 节点逻辑
│   └── progress.py           # Action/Observation 指纹与进展判断
├── policy/
│   ├── models.py             # PolicyDecision
│   ├── budget.py
│   ├── action.py
│   ├── observation.py
│   └── composite.py
├── contracts/
│   ├── models.py
│   ├── executor.py
│   └── registry.py
├── execution/
│   ├── action.py
│   ├── observation.py
│   └── executor.py           # Tool Runtime 管线
├── checkpoint/
│   ├── protocol.py
│   └── store.py
└── events/
    ├── events.py
    └── emitter.py
```

职责边界：

- Engine 只编排；
- Policy 不执行工具；
- Contract 不直接修改 Workflow；
- Tool Runtime 不决定阶段完成；
- HTTP 不感知 LangGraph 内部节点；
- 具体 Skill 规则不进入 `app/runtime`。

最终目录可在实施设计阶段按文件规模调整，但以上职责边界应保持。

---

## 22. 迁移路线

### Phase 0：冻结 Demo 基线

- 保存关键 Golden Cases；
- 固化正常、失败、取消、超时 SSE 序列；
- 保存各 Skill 的典型 Tool Trace；
- 明确当前 `turn`、DoneEvent 和 TurnRecord 测试语义；
- 当前 Runtime 进入仅修复严重缺陷状态。

### Phase 1：完成两条 P0 核心契约

#### P0-1 结构化决策通道

- 定义三个保留控制工具及 Pydantic schema；
- ToolCallsChunk 归一为 AgentDecision；
- 定义混合调用、多控制调用和纯文本的错误策略；
- 定义 `WAITING_INPUT` / `RunInputRequested`；
- 保证控制工具不进入 ToolBroker。

#### P0-2 ReAct/Workflow 接缝

- 定义 PhaseExecutionRequest；
- 定义 PhaseExecutionOutcome；
- 定义不可变 PhaseOutput；
- 定义 Workflow input bindings；
- 打通 complete → contract → repair/next/finalize 闭环。

此阶段使用测试 Workflow，不迁移现有 Skill 格式。

### Phase 2：实现单阶段 Bounded ReAct

实现：

```text
initialize
→ budget
→ decide
→ parse/validate decision
→ tool
→ progress
→ phase outcome
→ finalize
```

同时落实四项 P1：

- Phase 边界/副作用边界 Checkpoint；
- `RunCompleted(status=PARTIAL)`；
- 近似 no-progress；
- turn → phase iteration/step 指标迁移。

### Phase 3：迁移 Tool Runtime

- 接入现有 ToolBroker；
- 增加 preflight；
- 增加 Action/Observation fingerprint；
- 增加副作用与幂等元数据；
- 保持 MCP/Script 对上层透明。

### Phase 4：Checkpoint 与 Run API

- Run/Phase 边界 Snapshot；
- 副作用 Planned Action/Observation；
- stop/resume by run；
- 执行租约；
- Phase 级崩溃恢复；
- SSE 重连读取最新 Snapshot 并订阅后续事件。

### Phase 5：Workflow 与 Contract

- 支持多阶段 Workflow；
- 将现有 Gate 统一为 ContractExecutor；
- 实现有界修复和降级路径；
- 用 Adapter 迁移第一个现有 Skill。

### Phase 6：Skill Pack 格式决策与逐个迁移

在 V2 Core 验证后再决定是否引入 `skill.yaml`。迁移优先级：

1. 单阶段简单 Skill；
2. 有明确 Gate 的 Skill；
3. 报告型多阶段 Skill；
4. 需要复杂降级的数据密集型 Skill。

### Phase 7：切换与清理

- 通过 `agent_runtime_v2_enabled` 短期灰度；
- V2 达到验收标准后切换默认；
- 移除旧 Runtime、旧状态和双写兼容；
- 更新 `.ai/ARCHITECTURE.md` 与 `.ai/MODULE_MAP.md`。

不长期维护两套 Runtime。

## 23. 验收标准

### 23.0 P0 核心闭环

- [ ] `complete_phase` / `submit_final_answer` / `request_clarification` 均通过 ToolCall 通道产生；
- [ ] 控制工具不会进入 ToolBroker；
- [ ] 纯文本、混合控制/普通工具、多控制工具都有确定性处理；
- [ ] PhaseExecutionRequest/Outcome/PhaseOutput 均为类型化契约；
- [ ] complete → contract → repair/next/finalize 可完整闭环；
- [ ] 下一阶段只通过显式 input bindings 读取上游 PhaseOutput。

### 23.1 循环与预算

- [ ] 每条用户消息的迭代预算独立，不永久阻断后续会话；
- [ ] 正常 `react → tool → react` 不被误判为震荡；
- [ ] 相同 Action 但产生新 Observation 时允许继续；
- [ ] 相同 Action + 相同 Observation + 无进展达到阈值时终止；
- [ ] 重复动作在工具执行前被阻止；
- [ ] Token、时间、LLM、工具预算均可独立触发；
- [ ] 工作预算耗尽后仍保留最终输出预算；
- [ ] 硬预算耗尽后不再调用 LLM 或工具。

### 23.2 Contract

- [ ] 阶段完成必须通过确定性 Contract；
- [ ] Contract FAIL 不会无限修复；
- [ ] WARN、DEGRADE、PARTIAL、FAIL 行为明确；
- [ ] 平台代码中不存在具体业务 Contract 类；
- [ ] 现有 Gate 能通过统一 ContractExecutor 执行。

### 23.3 工具可靠性

- [ ] 工具参数在执行前通过 schema 验证；
- [ ] 工具可按阶段授权；
- [ ] 可重试与不可重试错误被区分；
- [ ] 副作用工具具有幂等键或明确的不可恢复策略；
- [ ] 工具执行前后均有 Checkpoint；
- [ ] 产物登记与 Observation 保持关联。

### 23.4 状态与恢复

- [ ] 普通子图节点不逐节点落库，进程重启从最近 Phase 边界恢复；
- [ ] 副作用工具执行前后均有 Checkpoint 和幂等/对账策略；
- [ ] 进程重启后 Run 可恢复或明确进入不可恢复终态；
- [ ] 同一 Run 不会被两个执行者并发推进；
- [ ] Runtime 状态不依赖进程内 `conversation_id → Runtime` 字典；
- [ ] RunState Snapshot 与事件 sequence 一致；
- [ ] 用户取消、预算终止、Contract 失败和内部异常严格区分。

### 23.5 接口与事件

- [ ] `RunCompleted(status=PARTIAL)` 明确携带 reason、limitations 和未完成阶段；
- [ ] 所有终态均发出明确结束事件；
- [ ] SSE 断开不会默认丢失 Run 状态；
- [ ] 事件包含 run/step/phase/sequence；
- [ ] HTTP 层不依赖内部 LangGraph 节点名称；
- [ ] blocking 与 streaming 返回相同的最终语义。

### 23.6 架构边界

- [ ] 平台 Runtime 中无具体 Agent/Skill/工具字面量；
- [ ] 跨生命周期状态使用 Pydantic；
- [ ] 外部 I/O 全部 async；
- [ ] 具体实现由 bootstrap 组合，Runtime 依赖抽象；
- [ ] Workflow 控制存在于 LangGraph，不依赖提示词自然语言推进；
- [ ] 变更通过 ruff、mypy 与 pytest。

---

## 24. 测试策略

### 单元测试

- Policy 每种 Decision；
- Budget 软/硬边界；
- Action/Observation fingerprint；
- no-progress 算法及已知误杀/漏过边界；
- Contract retry/degrade/fail；
- Workflow 条件边；
- 状态模型序列化；
- AgentDecision 的控制工具映射；
- PhaseExecutionRequest/Outcome 闭环；
- current turn 到 phase iteration/step 的指标映射。

### 图级测试

使用确定性 Fake LLM 脚本化返回：

- 工具调用后正常完成；
- 无限重复同一 Action；
- A/B 工具交替但无进展；
- 重复 Action 但每次有新进展；
- Contract 两次失败后成功；
- Contract 达到修复上限；
- Finalization Reserve 生效。

### 集成测试

- MCP/Script 统一执行；
- Checkpoint 后恢复；
- 工具执行中取消；
- SSE 断开与重新订阅；
- 两执行者竞争同一 Run；
- 副作用工具崩溃恢复；
- 产物登记与下载。

### Golden Case

每个正式 Skill 至少维护：

- 正常成功；
- 数据源降级；
- 部分完成；
- 无进展终止；
- Contract 失败；
- 用户取消。

---

## 25. 明确拒绝的方案

### 25.1 在完整 run_turn 外包装 Guard

原因：无法观察或中断图内部 `react ⇄ tool` 循环。

### 25.2 根据状态节点名称检测震荡

原因：ReAct 正常拓扑本身就是节点交替，误判率高。

### 25.3 仅用最大轮次解决死循环

原因：只能保证终止，不能识别重复、控制成本或生成高质量部分结果。

### 25.4 由 LLM 自行声明阶段成功

原因：概率输出不能作为确定性完成条件。

### 25.5 在平台中编写具体 Skill Contract

原因：破坏平台与业务包边界，新增 Skill 会修改 Runtime。

### 25.6 用另一个自由 Supervisor 实现多 Agent

原因：会将单 Agent 循环扩大为多 Agent 协调循环。

### 25.7 长期并存两套 Runtime

原因：状态、事件、工具和持久化会形成双重事实来源，只允许短期灰度迁移。

---

## 26. 最终架构定义

正式 Agent Runtime 的职责可以总结为：

```text
Workflow 决定当前执行哪个阶段；
ReAct 在阶段内提出下一步动作；
Policy 决定动作是否允许；
Tool Runtime 负责可靠执行；
Progress Monitor 判断是否产生进展；
Contract 决定阶段是否真正完成；
Checkpoint 保证执行可以恢复；
Event 负责对外呈现、落库和审计；
Finalize 保证任何终止路径都有明确可交付结果。
```

当前 Demo 的价值在于已经验证外围链路。V2 的重点不是继续扩大 Demo Runtime，而是将这些已验证能力组装到一个有界、可恢复、可观测、业务无关的正式执行内核中。

---

**文档结束**
