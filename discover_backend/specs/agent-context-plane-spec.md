# Agent 上下文平面规范

> **规范性质**：Agent 上下文平面的结构、边界、生命周期与迁移约束；含分阶段实施边界。  
> **关联文档**：`docs/ARCHITECTURE.md`、`docs/MODULE_MAP.md`、`.claude/feature/react-runtime-v2-architecture.md`  
> **核心决策**：统一 Agent 可见上下文的构造入口和结构化模型，但不把 Run 控制状态、会话事实、文件事实和 ReAct 临时工作状态粗暴合并为一个巨型 State。

**权威来源**：本规范只定义稳定的目标结构、边界与阶段约束，不记录当前实现进度、日期或阶段状态；当前实现事实以 `docs/ARCHITECTURE.md` 为准，职责与路径以 `docs/MODULE_MAP.md` 为准。

---

## 1. 适用场景 / 不适用场景 / 职责边界与权威来源

### 1.1 适用场景

本方案适用于：

- Agent / ReAct 执行上下文重构；
- 会话历史、当前用户消息、文件附件、工具观察、阶段输出的统一建模；
- LangGraph 节点状态与 Run 状态之间的边界调整；
- 上下文压缩、摘要、消息投影和 Token 预算控制；
- Agent 任务恢复、Checkpoint、事件日志与上下文版本关联；
- 多阶段 Workflow 对上下文的传递；
- 用户文件与消息、Run、Artifact 的关联；
- 未来多 Agent 协作、系统主动触达和 role-based message 流演进。

### 1.2 不适用场景

本方案不负责：

- LLM Provider 的 HTTP 协议、模型参数和流式分片解析；
- ToolBroker 的工具发现、工具授权和工具调用协议；
- Agent / Skill manifest 字段定义；
- 文件字节存储后端的具体实现；
- 会话 API 的具体响应格式；
- 前端状态管理；
- 具体业务领域的提示词正文；
- 使用自然语言提示词替代 Runtime 状态机、Policy 或 Contract。

### 1.3 职责边界与权威来源

- 本文定义 Agent 上下文的结构、边界、生命周期、版本和迁移约束。
- 当前代码事实以 `docs/ARCHITECTURE.md` 为准。
- 当前职责与路径以 `docs/MODULE_MAP.md` 为准。
- 当前 ReAct 拓扑以 `app/harness/graph.py` 和 `app/harness/react/executor.py` 为准，
  阶段内决策 / Policy / Contract 判定以 `app/harness/{decision,progress,policy,contracts}/` 为准。
- 会话持久化以 `app/application/conversation/` 与 `app/infrastructure/database/` 为准。
- 文件元数据与字节存储以 `app/application/file/` 和 `app/environment/storage/` 为准。
- 本文是目标架构和重构约束，不得把未实现内容描述为当前事实。

---

## 2. 背景与问题定义

### 2.1 当前设计已经存在状态管理，但职责不完整

当前系统并非没有状态管理，已有以下状态对象：

```text
RunState
  └── Run / Workflow / Budget / Cancellation / Termination / Output

ReactGraphState
  └── 当前 Phase 内的 messages / tool calls / observations / progress

ConversationService
  └── conversations + messages 持久化与历史读取

FileService / Storage
  └── upload_files 元数据 + 文件字节

EventLog / SnapshotStore
  └── Run 事件与快照协议
```

这些对象分别解决了运行控制、阶段执行、会话审计、文件存储和恢复协议问题。

当前短板不是缺少一个“总状态对象”，而是缺少一个统一的、结构化的上下文平面：

```text
Conversation / File / Run / Observation / Artifact / Memory
                         ↓
              缺少统一 Context Assembly
                         ↓
          context_summary 字符串或局部字段
                         ↓
                    ReAct LLM
```

### 2.2 当前专家路径的上下文问题

当前专家 ReAct 路径主要通过 `PhaseExecutionRequest.context_summary` 传入历史摘要，并在 `react_prepare` 中拼入 system prompt。

当前行为近似为：

```text
system
  ├── Agent / Skill 系统提示
  ├── 阶段目标
  ├── 阶段输入，其中包含 user_goal
  └── 上下文摘要字符串
```

而不是：

```text
system
历史 user / assistant messages
当前 user message
当前阶段结构化输入
```

这会导致：

- 历史消息的 role 语义被压扁；
- 当前用户消息没有作为独立的 `role=user` 进入模型；
- 历史内容、用户内容和系统约束的边界不清晰；
- 无法稳定追踪 `message_id`、文件引用和证据引用；
- 工具观察仅存在于当前 ReAct 图的临时 messages 中；
- 未来多阶段、多 Agent、恢复和重放能力受限。

### 2.3 当前文件上下文问题

当前文件能力已经存在：

```text
FileService
upload_files
Storage
ArtifactRecord
ObservationRecord.artifact_ids
RunOutput.artifact_ids
```

但用户上传文件尚未作为本轮消息的规范化附件进入 Agent Context。现有聊天请求文档提到 `files`，实际请求模型尚未形成完整的附件契约；用户文件、当前 message、Run、Phase 和 Agent 之间也没有统一的上下文关联模型。

### 2.4 当前消息持久化问题

当前 `messages` 表将 `query / answer / thinking` 拍平为一行，适合现有聊天历史接口和一问一答范式，但不能完整表达：

- assistant tool calls；
- tool result；
- observation；
- artifact 引用；
- 多 Agent 消息；
- 系统主动消息；
- parent / reply 关系；
- 工具调用失败与重试轨迹。

该问题已经属于演进型技术债。本次重构不得直接删除现有模型，而应先通过运行时上下文适配和增量持久化解决。

---

## 3. 核心架构决策

### 3.1 四类对象必须分离

Agent Runtime 必须区分：

```text
RunState
AgentContext
ReactWorkingState
Source Stores
```

不得把四类对象合并为一个“万能 Context”。

### 3.2 RunState 是运行控制平面

`RunState` 负责一次 Run 的控制和生命周期：

```text
身份
目标
Workflow
Phase 状态
预算
取消
终止
阶段摘要
最终输出摘要
审计版本
```

`RunState` 可以保存上下文引用和摘要，但不得保存完整业务上下文正文。

禁止将以下内容作为 RunState 的长期字段：

- 完整 conversation message 历史；
- 完整文件正文或二进制内容；
- 完整工具原始输出；
- 每次 LLM 请求的全部 prompt；
- 任意业务数据的无约束共享字典。

### 3.3 AgentContext 是统一上下文平面

必须引入结构化的 `AgentContext`，表示 Agent 在某个执行时点能够看到的上下文快照。

`AgentContext` 是：

```text
Agent 可见信息的结构化快照
```

不是：

```text
所有业务事实的永久主存储
```

AgentContext 必须包含来源、引用、版本和裁剪结果，而不是无边界复制所有来源数据。

### 3.4 ReactWorkingState 是阶段内工作平面

现有 `ReactGraphState` 或重命名后的 `ReactWorkingState` 只负责当前 Phase 内部的短生命周期执行状态：

```text
当前 LLM messages
pending tool calls
当前 decision
最近 observation
Action / Observation 记录
预算增量
进展检测
修复次数
终止原因
阶段 outcome
```

它可以持有 `AgentContext` 的只读快照或投影结果，但不得成为跨会话、跨 Run 的长期事实存储。

### 3.5 Source Stores 保持唯一事实来源

| 数据 | 权威来源 |
|---|---|
| 会话消息 | `ConversationService` / Conversation Store |
| 文件元数据 | `FileService` / `upload_files` |
| 文件内容 | `Storage` |
| Run 控制状态 | `SnapshotStore` |
| Run 事件 | `EventLog` |
| 工具观察 | Observation 记录 / EventLog |
| 阶段输出 | `PhaseOutput` / Run checkpoint |
| 长期用户记忆 | 独立 Memory Store |

AgentContext 可以保存：

```text
引用
摘要
受控快照
版本
来源元数据
```

不得成为上述事实来源的第二个无约束主存储。

---

## 4. 目标上下文模型

### 4.1 顶层模型

推荐新增一个独立的上下文模型模块，例如：

```text
app/environment/context/          # 事实模型 + 来源端口（系统有哪些事实）
    __init__.py
    models.py
    ports.py
app/harness/context/              # 上下文编译器（本轮取舍/裁剪/投影；P1#9 从 environment 拆出）
    __init__.py
    assembler.py
    projector.py
# reducer.py / policy.py 属后续阶段（阶段六 / 契约接线）
```

最终模型形态应接近：

```python
class AgentContext(BaseModel):
    identity: ContextIdentity
    current_input: CurrentInput
    conversation: ConversationContext
    attachments: AttachmentContext
    memory: MemoryContext
    workflow: WorkflowContext
    evidence: EvidenceContext
    artifacts: ArtifactContext
    constraints: ContextConstraints
    version: int = 1
```

所有跨边界模型必须使用 Pydantic v2 `BaseModel`。

禁止使用一个无边界的：

```python
dict[str, object]
```

作为完整 Agent Context 的长期替代方案。`dict[str, object]` 仍可用于明确的 Phase 输入、工具参数和业务 payload，但不得充当统一上下文模型。

### 4.2 ContextIdentity

至少需要：

```text
run_id
conversation_id
message_id
account_id
phase_instance_id
context_version
```

其中：

- `account_id` 用于权限和租户隔离；
- `conversation_id` 用于跨回合历史；
- `message_id` 表示本轮当前输入；
- `run_id` 表示本次执行；
- `phase_instance_id` 表示当前阶段；
- `context_version` 用于审计、重放和恢复。

### 4.3 CurrentInput

当前输入必须是独立结构化对象：

```text
text
message_id
file_ids / attachments
metadata
```

当前用户消息必须以 `role=user` 或等价的结构化消息进入 LLM 上下文。

禁止仅通过下列方式传递当前用户输入：

```python
system_prompt += f"用户目标：{user_input}"
```

或：

```python
phase_input={"user_goal": user_input}
```

然后依赖 system prompt 拼接给模型。

`phase_input` 的职责是 Phase 的结构化输入，不是当前用户消息的替代品。

### 4.4 ConversationContext

会话上下文至少应支持：

```text
summary
recent_messages
pinned_messages
message_refs
covered_message_range
```

消息必须保留至少以下语义：

```text
message_id
conversation_id
role
content
created_at
parent_id（若模型已支持）
metadata
```

运行时至少需要支持以下角色：

```text
system
user
assistant
tool
observation
artifact
```

当前 `query / answer / thinking` 单行模型可以在迁移期继续兼容，但不得成为新的运行时上下文抽象。

### 4.5 AttachmentContext

附件上下文至少应支持：

```text
file_id
message_id
conversation_id
run_id
created_by
created_by_role
name
media_type
size_bytes
storage_ref
extraction_status
access_scope
```

用户上传文件和 Agent 生成产物必须可区分：

```text
user_upload
agent_artifact
external_reference
```

AgentContext 默认只保存：

```text
FileRef
ExtractedTextRef
ParsedTableRef
ArtifactRef
```

不得默认把整个文件内容复制进 LangGraph State。

文件内容需要进入上下文时，必须通过：

```text
Context → FileRef → FileService / Storage / Parser
```

执行受控读取。

### 4.6 EvidenceContext

工具结果和外部资料进入上下文时，应至少保留：

```text
observation_id
source_ref
content_summary
content_blob_ref
confidence
created_at
truncated
artifact_ids
```

完整原始结果应存放在对应的 Store 或 Blob 中；上下文中只保留模型当前所需的摘要、引用和截断标记。

### 4.7 WorkflowContext

多阶段上下文至少包括：

```text
current_phase_id
phase_goal
phase_input
upstream_outputs
completed_phase_ids
pending_requirements
```

阶段输出必须继续使用结构化的 `PhaseOutput`，阶段之间不得共享可变对象。

### 4.8 ContextConstraints

上下文可以携带 Agent 可见的业务约束：

```text
allowed_tools
output_contract_refs
access_scope
locale
timezone
context_token_budget
```

但以下字段仍属于 Runtime 控制平面，不得被用户消息、文件正文或工具结果直接修改：

```text
budget usage / limits
cancel_requested
lease
termination
```

---

## 5. Context Assembly、Reduction 与 Projection

### 5.1 ContextAssembler 是统一入口

必须引入 `ContextAssembler`，统一从事实来源构建 `AgentContext`。

职责包括：

```text
加载会话历史
加载当前消息
加载消息附件
加载阶段输入和上游输出
加载最近工具观察
加载已有产物引用
应用账号隔离与访问策略
执行上下文选择和预算裁剪
生成带版本的 AgentContext
```

ContextAssembler 不负责：

- LLM 调用；
- 工具调用；
- Workflow 路由；
- 数据库结构迁移；
- SSE 输出；
- 修改 Run 控制状态。

当前分散在 `app/application/chat/run_turn.py` 的以下逻辑应逐步下沉：

```text
_load_history
_history_summary
LLM messages 拼接
附件加载
上下文裁剪
```

### 5.2 ContextReducer 负责应用上下文增量

工具执行、阶段完成和用户补充信息都应形成结构化 `ContextDelta`：

```python
class ContextDelta(BaseModel):
    messages: list[ContextMessage] = Field(default_factory=list)
    observations: list[ObservationRef] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    memory_updates: list[MemoryUpdate] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
```

处理链路：

```text
Tool Result
    ↓
Observation Normalizer
    ↓
ContextDelta
    ↓
ContextReducer
    ↓
AgentContext(version + 1)
```

工具不得直接修改 Conversation、Run 或其他 Agent 的共享状态。

### 5.3 ContextProjector 统一生成 LLM messages

结构化 `AgentContext` 必须通过 `ContextProjector` 投影为：

```python
list[ChatMessage]
```

推荐投影顺序：

```text
1. system prompt
2. durable task constraints
3. conversation summary
4. selected conversation messages
5. attachment references
6. selected evidence / observations
7. current user message
```

要求：

- 系统约束保持 `role=system`；
- 用户内容保持 `role=user`；
- 工具结果保持 `role=tool` 或明确的 observation 语义；
- 当前用户消息不可被摘要替代；
- 文件正文必须标注来源和文件引用；
- 不可信外部内容不得伪装为 system 指令；
- 投影结果必须可独立测试和重放。

### 5.4 通用对话与专家 ReAct 共享上下文构造规则

通用路径和专家路径可以有不同的系统提示与工具集合，但必须共享：

```text
ConversationContext 加载
CurrentInput 处理
AttachmentContext 处理
上下文裁剪规则
ContextProjector 的消息语义
```

不得在通用路径和专家路径分别维护两套互相漂移的历史拼接逻辑。

---

## 6. 上下文裁剪和 Token 预算

### 6.1 裁剪必须确定性

上下文裁剪不得使用随机策略，必须可测试、可重放。

建议优先级：

```text
1. 当前用户消息
2. 平台安全约束和系统提示
3. 当前 Phase 必需输入
4. 当前任务相关附件引用
5. 最近对话消息
6. 当前 Run 的关键观察
7. 阶段输出和证据引用
8. 较早历史摘要
9. 非关键工具原始结果
```

### 6.2 保留引用，不因裁剪丢失可追踪性

原始工具结果、文件正文或早期消息被裁剪时，必须保留：

```text
message_id
file_id
observation_id
artifact_id
source_ref
truncated
```

完整内容应可通过受控引用重新获取。

### 6.3 摘要必须可追踪

摘要对象至少应记录：

```text
summary
source
covered_message_range
source_message_ids
created_at
context_version
```

字符串摘要可以作为 LLM 投影的一部分，但不得作为唯一的领域上下文模型。

---

## 7. 文件、消息和 Artifact 关联约束

### 7.1 聊天请求必须表达附件引用

聊天请求应支持结构化附件引用，推荐字段：

```text
file_ids: list[str]
```

如需要扩展，应使用 Pydantic 模型而不是散落的自由字段。

### 7.2 附件关联必须可审计

至少应能回答：

- 文件属于哪一轮消息？
- 文件属于哪个会话和 Run？
- 文件是用户上传还是 Agent 生成？
- 当前 Agent 是否有读取权限？
- 文件是否已经解析？
- 当前上下文引用的是原文件、抽取文本还是解析表格？
- 文件是否被工具消费过？

推荐通过关联模型或等价持久化结构支持：

```text
conversation_id
message_id
run_id
file_id
role
created_at
```

### 7.3 不直接把文件正文放入 Graph State

文件正文、图片二进制和大表格数据必须保留在 Storage 或解析结果 Store。Graph State 只携带：

```text
文件引用
解析结果引用
受限摘要
必要的小型结构化片段
```

---

## 8. 工具观察、产物和阶段输出

工具执行后必须能够产生：

```text
new_observations
new_artifacts
new_evidence
updated_facts
limitations
```

产物引用必须在以下层之间保持一致：

```text
ToolResult
ObservationRecord
ContextDelta
PhaseExecutionOutcome
PhaseOutput
RunOutput
Conversation / Artifact persistence
```

阶段输出不得只通过自然语言摘要传递。至少需要保留：

```text
phase_id
schema_version
data
evidence_refs
artifact_ids
limitations
degraded_sources
contract_results
produced_at
```

多阶段 Workflow 的下一阶段只能通过 `input_bindings`、`upstream_outputs` 或 ContextAssembler 读取上游结果，不得通过全局变量或共享可变字典传递。

---

## 9. Checkpoint、事件和恢复

### 9.1 上下文版本必须可恢复

每个 AgentContext 快照至少关联：

```text
run_id
conversation_id
message_id
phase_instance_id
context_version
source message ids
source file ids
source observation ids
source artifact ids
```

以下事件必须使上下文产生新版本或可确定地生成新版本：

- 新用户消息；
- 工具调用完成；
- 文件解析完成；
- 阶段输出固化；
- 用户补充信息；
- ContextReducer 应用新的 ContextDelta；
- 上下文摘要更新。

### 9.2 恢复粒度必须诚实声明

恢复至少应能够重建：

```text
RunState
AgentContext version
current phase
current iteration
messages 或 message references
pending actions
observations
budget usage
termination / cancellation
```

如果只能在 Phase 边界恢复，必须明确声明：

```text
Phase boundary resume
```

如果不能恢复 LangGraph 内部节点，不得在文档或 API 中声称支持完整节点级断点恢复。

### 9.3 EventLog 与 ContextDelta

RunEvent 是外部事件和审计出口；ContextDelta 是上下文语义更新对象。二者可以关联，但职责不同：

```text
RunEvent    = 运行生命周期和观测事件
ContextDelta = Agent 可见上下文的结构化增量
```

不得用 SSE 文本帧作为上下文事实来源。

---

## 10. 严格禁止事项

以下重构方式禁止采用：

1. 将所有数据塞入一个 `ReactGraphState`；
2. 将完整文件内容放入 `RunState` 或每个 Graph 节点；
3. 将 conversation 历史直接拼进 system prompt 并丢失 role；
4. 让当前用户消息只存在于 `phase_input["user_goal"]`；
5. 在 HTTP 路由中继续手工维护多套上下文拼接逻辑；
6. 通过模块级全局变量保存会话上下文；
7. 让 Agent 包直接访问平台数据库或文件目录；
8. 让工具自行修改 Conversation、Run 或其他 Agent 状态；
9. 用 `dict[str, object]` 替代结构化上下文模型；
10. 一次性删除现有 `messages` 表或会话 API；
11. 没有迁移和兼容测试就改变现有历史语义；
12. 文档声称支持恢复，但不保存上下文版本和来源引用；
13. 让用户消息、文件内容或工具返回结果直接修改预算、取消、租约或终止状态；
14. 使用提示词自然语言决定 Phase 路由、工具授权、预算终止或 Contract 结果；
15. 为了“统一上下文”而跨越 Conversation、File、Runtime 和 Infrastructure 的依赖方向。

---

## 11. 分阶段实施方案

本方案必须分阶段实施，不允许一次性进行全量数据库和运行时重写。

### 阶段一：建立纯模型层

目标：引入结构化模型，不改变对外 API 和当前执行行为。

建议新增：

```text
AgentContext
ContextIdentity
CurrentInput
ConversationContext
ContextMessage
AttachmentContext
FileRef
EvidenceContext
ObservationRef
ArtifactContext
WorkflowContext
ContextConstraints
ContextDelta
```

要求：

- 全部使用 Pydantic v2；
- 模型可序列化和反序列化；
- 不直接依赖 FastAPI、SQLAlchemy ORM、httpx 客户端或具体存储实现；
- 为模型 round-trip 和字段边界添加单元测试。

### 阶段二：建立 Source Ports 和 ContextAssembler

从 `app/application/chat/run_turn.py` 抽离：

```text
_load_history
_history_summary
附件读取
历史裁剪
LLM 消息拼接前的上下文准备
```

Assembler 通过构造函数注入抽象 Port：

```text
ConversationContextPort
AttachmentContextPort
ObservationContextPort
ArtifactContextPort
```

Assembler 不直接在核心模型中实例化 SQLAlchemy、Storage 或第三方客户端。

### 阶段三：建立 ContextProjector

统一将 `AgentContext` 投影为 `list[ChatMessage]`。

要求：

- 保持 role 语义；
- 当前用户消息为独立 user message；
- 历史消息与 system prompt 分离；
- 文件和工具观察使用引用、摘要和来源标记；
- 具备确定性裁剪策略；
- 为每种输入类型添加独立单测。

### 阶段四：专家 ReAct 接入结构化上下文

将当前专家路径从：

```text
PhaseExecutionRequest.context_summary
    ↓
system prompt 字符串
```

迁移为：

```text
AgentContext
    ↓
ContextProjector
    ↓
ReactGraphState.messages
```

`PhaseExecutionRequest.context_summary` 可在兼容期保留，但不得继续作为唯一上下文入口。完成迁移后，再评估删除或降级为摘要字段。

### 阶段五：接入消息附件

增加当前消息的 `file_ids` 或结构化附件字段，并建立消息与文件的稳定关联。

要求：

- 保持现有文件上传 API 兼容；
- 不把文件正文直接写入消息表；
- 增加权限、归属和关联校验；
- 增加用户上传、Agent 产物和外部引用的来源类型。

### 阶段六：接入 ContextDelta

将工具结果、产物、Observation 和阶段输出统一转换为上下文增量，并由 ContextReducer 应用。

要求：

- 不修改 ToolBroker 的职责边界；
- 不让工具自行写入 Conversation 或 Run；
- 不丢失 artifact_id、observation_id 和 source_ref；
- 对重复观察和截断结果保留明确标记。

### 阶段七：接入 Checkpoint / Resume

在现有 `RunService`、`SnapshotStore`、`EventLog` 基础上关联：

```text
run_id
phase_id
context_version
checkpoint
```

先明确支持的恢复粒度，再实现对应持久化和测试；不得先实现“看起来能恢复”但语义不完整的接口。

### 阶段八：演进 role-based message 持久化

在兼容现有 `query / answer / thinking` 读取接口的前提下，逐步支持：

```text
role
content
parent_id
tool_call_id
tool_name
metadata
run_id
phase_id
```

迁移期间可采用双写、事件表或兼容视图，但必须通过 Alembic 管理结构变化，不得手工修改数据库。

---

## 12. AI 重构执行约束

让 AI 执行本方案时，必须提供以下上下文文件：

```text
AGENTS.md
CLAUDE.md
docs/ARCHITECTURE.md
docs/MODULE_MAP.md
specs/INDEX.md
specs/agent-context-plane-spec.md
```

AI 必须按以下顺序工作：

1. 先读取当前架构事实和模块地图；
2. 输出当前实现与目标架构的差异清单；
3. 识别本次任务所属实施阶段；
4. 只修改当前阶段允许的文件边界；
5. 修改前先说明依赖方向和数据权威来源；
6. 每个新增跨边界模型配套单元测试；
7. 不自行扩大为数据库迁移、API 破坏性变更或全量重写；
8. 发现需要新增表、迁移或改变外部契约时，先报告影响，不隐式执行；
9. 完成后运行格式、静态检查、相关单测和必要的 mypy；
10. 更新 `docs/ARCHITECTURE.md` 和 `docs/MODULE_MAP.md` 仅限于实际完成的结构变化。

推荐给 AI 的任务提示：

```text
请严格依据 AGENTS.md、CLAUDE.md、docs/ARCHITECTURE.md、docs/MODULE_MAP.md
以及 specs/agent-context-plane-spec.md 执行本次任务。

本次只实现指定实施阶段，不跨阶段重构。

要求：
1. 先输出当前实现与目标约束的差异清单；
2. 明确本次修改的文件边界、权威数据来源和依赖方向；
3. 不将所有上下文塞进 ReactGraphState；
4. 不直接把完整文件正文放进 RunState 或 Graph State；
5. 不删除现有 ConversationService、消息 API 或文件 API；
6. 不绕过 Alembic 修改数据库结构；
7. 不让 Runtime 核心直接实例化 SQLAlchemy、Storage 或外部客户端；
8. 新增模型和核心逻辑必须配套 tests/unit 测试；
9. 完成后运行 ruff format、ruff check、mypy 和无 DB 的 tests/unit；
10. 最后报告已完成内容、未完成内容、兼容风险和后续阶段建议。
```

---

## 13. 验收标准

### 13.1 上下文模型

- [ ] AgentContext 使用 Pydantic v2；
- [ ] AgentContext 可以序列化、反序列化；
- [ ] AgentContext 有 context version；
- [ ] 上下文元素有 source reference；
- [ ] 当前用户输入是独立结构化消息；
- [ ] conversation、file、observation、artifact 可以分别追踪；
- [ ] 统一上下文不是无边界的 `dict[str, object]`。

### 13.2 ReAct

- [ ] ReAct 不直接访问数据库或存储；
- [ ] ReAct 可以接收结构化 AgentContext；
- [ ] ReactGraphState 只保存阶段内工作态；
- [ ] 工具结果可以转换为 ContextDelta；
- [ ] 上下文裁剪不会丢失关键引用；
- [ ] LLM messages 投影逻辑可独立测试；
- [ ] 当前 user message 不再只存在于 system prompt 字符串中。

### 13.3 文件

- [ ] 请求可以声明附件；
- [ ] 附件与 message / conversation / run 至少有稳定关联；
- [ ] 文件正文不默认复制进 Graph State；
- [ ] 文件访问经过 FileService、Storage 或明确的 Port；
- [ ] Agent 产物与用户上传可区分；
- [ ] 文件引用经过账号和访问范围校验。

### 13.4 历史

- [ ] 现有 query / answer / thinking API 保持兼容；
- [ ] 新上下文层不依赖单行问答模型作为唯一抽象；
- [ ] 工具观察和产物可以被审计或重放；
- [ ] 错误、部分完成、中断回合不会破坏上下文构造；
- [ ] 历史摘要具备来源和覆盖范围信息。

### 13.5 恢复和质量

- [ ] Context version 与 Run / Phase 可关联；
- [ ] 支持的恢复粒度有明确文档和测试；
- [ ] 不存在真实 HTTP、真实数据库和阻塞 I/O 的单元测试依赖；
- [ ] Python 变更完成 `ruff format`、`ruff check`、相关 pytest 和必要的 mypy；
- [ ] 实际完成结构变化后同步 `docs/ARCHITECTURE.md` / `docs/MODULE_MAP.md`。

---

## 14. 首个实施任务建议

首个 AI 重构任务只做以下范围：

```text
新增结构化 AgentContext 纯模型
新增 ContextMessage / CurrentInput / ConversationContext
新增 ContextAssembler 的抽象 Port 和最小实现
新增 ContextProjector
将专家 ReAct 的当前用户输入改为独立 role=user message
保留现有 context_summary 作为兼容字段
不修改数据库表
不新增 Alembic migration
不修改对外响应格式
```

首个任务明确不做：

```text
role-based message 数据库迁移
文件正文解析系统
LangGraph 持久化 Checkpointer 全量接入
长期 Memory Store
多 Agent 协作协议
```

首个任务完成后，必须先验证：

```text
system + history + current user message
```

在专家 ReAct 和通用对话路径中的消息语义一致，再进入附件、ContextDelta 和恢复能力建设。

---

## 15. 本规范专属检查

- [ ] Agent 可见上下文只有一个构造入口（ContextAssembler），调用方不再各自拼接历史
- [ ] 当前用户消息是独立 `role=user` 消息，未压平进 system prompt 或仅存于 `phase_input`
- [ ] 会话历史保留 role 语义，且历史内容不得伪装为 system 约束
- [ ] AgentContext 只保存引用、摘要、版本与来源元数据，未复制文件正文或工具原始输出
- [ ] 上下文对象未退化为无边界 `dict[str, object]`
- [ ] 裁剪与摘要策略确定性可测，裁剪后仍保留 message_id / file_id / observation_id 等引用
- [ ] 预算、取消、租约与终止仍属 Runtime 控制平面，未被上下文内容直接修改
- [ ] 事实来源仍是 Conversation / File / Run / Observation / Artifact 各 Store，未出现第二主存储
- [ ] 运行时核心未直接实例化 SQLAlchemy、Storage 或外部客户端，依赖经端口注入
- [ ] 结构变化后已同步 `docs/ARCHITECTURE.md` 与 `docs/MODULE_MAP.md`
