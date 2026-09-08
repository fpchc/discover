# 技能装配规范

## 适用场景

- 修改技能解析策略、SkillAssembler 或 AssemblyPlan
- 调整系统提示拼接、能力解析、门禁脚本注册
- 排查技能选择、依赖降级或装配结果错误

## 不适用场景

- 定义 AGENT / SKILL 清单字段
- 执行 MCP 调用、工具调用或阶段状态机

## 职责边界与权威来源

本文件定义“如何把已校验清单转换成装配计划”。清单字段见 `agent-package-spec.md`；工具目录与分发见 `tool-broker-spec.md`；当前代码路径见 `.ai/MODULE_MAP.md`。

## 1. 层次边界

- Resolver：确定性选择 skill_id，不构造上下文。
- Assembler：读取已加载清单，计算 `AssemblyPlan`，不启动服务、不发事件。
- Runtime：执行计划，管理生命周期、阶段、事件和终止。
- ToolBroker：根据计划激活工具目录并分发调用，不参与技能选择。

判定标准：**计算“应该做什么”属于装配；执行“现在去做”属于运行时。**

## 2. 技能解析

解析必须确定性、可测试，不用 LLM 判断：

```text
显式 skill_id → default_skill → 唯一技能 → 首个技能
```

输入只包含已选智能体的合法技能。显式 ID 不存在、无可用技能或清单不完整时抛注册校验异常，不猜测相近名称。

## 3. AssemblyPlan 契约

装配结果使用 Pydantic 模型，至少包含：

| 字段 | 用途 |
|---|---|
| `agent_id` / `skill_id` | 本次身份 |
| `system_prompt` | 已组装系统上下文 |
| `required_mcp_servers` / `optional_mcp_servers` | 启用且应由 Runtime 处理的服务 |
| `mcp_degrade_notes` | 可选服务的降级说明 |
| `capabilities` | `CapabilityPlan` 列表 |
| `core_tool_names` | 预暴露工具 |
| `scripts` | 技能脚本与门禁校验器 |
| `env_whitelist` | 脚本环境变量白名单 |
| `model_preference` / `thinking_preference` | 运行偏好 |

不得把客户端、会话、锁、文件句柄等运行时对象放入计划。

## 4. 系统提示组装

拼接顺序固定：

```text
智能体展示名与 Agent 正文
技能职责与 Skill 正文
参考文档索引（路径 + 读取时机）
模板索引（路径 + 用途）
门禁索引（ID + 条件）
平台强制红线
```

要求：

- 不预加载参考文档全文，只注入索引；按需通过工具读取。
- 不重复注入 frontmatter 中已经由代码消费、且模型无需知道的字段。
- 平台红线恒在末尾，技能正文不得覆盖。
- 系统提示不包含服务当前状态、端口、密钥或历史迁移说明。
- 平台红线至少要求使用 `display_name`，并禁止在用户可见输出中泄露内部 ID、路径和工具命名空间。

## 5. MCP 与能力解析

### 具体服务

- `enabled: false` 的服务从计划中剔除，不尝试连接。
- 启用且 `required: true` 的服务进入 required 列表。
- 启用且可选的服务进入 optional 列表，并携带降级说明。

### CapabilityPlan

- 能力必须已注册，否则 fail-fast。
- `candidate_servers` 只包含启用服务。
- `strategy=failover` 保留注册表候选顺序；Runtime 负责逐个尝试。
- `strategy=all` 激活所有候选，不应用 fallback。
- fallback 只允许注册表定义的一级降级；目标缺失或继续声明 fallback 时拒绝加载。

装配层只解析计划，不探测网络可用性。

## 6. 门禁校验器注册

声明了 validator 的 gate 转换为只读脚本工具，并加入计划的 scripts。工具名必须确定、可追踪且不与技能脚本冲突。无 validator 的 gate 仅作为弱约束注入提示词，不得假装已经被程序验证。

## 7. 降级语义

| 情况 | 装配结果 | Runtime 行为 |
|---|---|---|
| 服务被配置禁用 | 不进入计划 | 不连接、不报启动错误 |
| 必需服务启动失败 | 保留 required 声明 | 发错误并终止本轮 |
| 可选服务启动失败 | 保留说明 | 发降级事件后继续 |
| failover 候选失败 | 保留有序候选 | 尝试下一候选 |
| 所有候选失败且存在 fallback | 携带 fallback 候选 | 按计划降级 |

## 8. 本规范专属检查

- [ ] Resolver 确定性选择且不构造上下文
- [ ] Assembler 不启动服务、不执行工具、不发事件
- [ ] 系统提示顺序稳定且无不必要重复
- [ ] disabled、required、optional、failover、all、fallback 语义清晰
- [ ] 计划只含可序列化数据模型，不含运行时句柄
