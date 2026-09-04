# 技能装配规范（Skill Assembly）

## 适用场景 / 何时触发

- 实现 / 修改技能解析策略链（SkillResolver）或装配逻辑（SkillAssembler）时
- 调整系统提示组装、依赖 / 能力解析、门禁校验器注册时
- 排查「技能没选中、装配出错误技能、必需依赖未拒绝激活、降级未生效」时
- 判断某段装配逻辑该放 L2 装配层还是 L3 运行时节点时

---

## 1. 职责边界

装配层（L2）负责**选技能 + 算出装配计划**；运行时 assemble 节点（L3）负责**执行计划**。
两者不重复，也不互相越界：

| 归属 | 内容 |
|------|------|
| L2 装配层（本文件） | SkillResolver 策略链、SkillAssembler 装配计划（`AssemblyPlan`）、系统提示组装、MCP 依赖 / 能力解析、门禁校验器注册 |
| L3 运行时（Agent Runtime V2，见 `react-runtime-v2-architecture.md`） | 执行 `AssemblyPlan`：启动 MCP 依赖、注入上下文、激活工具、发就绪 / 降级 / 错误事件 |
| L2 工具代理（`tool-broker-spec.md`） | 接收暴露集合、维护目录、分发调用，不参与装配决策 |

判定标准：**算得出来什么 → 装配层；拿计划去干活 → 运行时。**

---

## 2. 技能解析策略链

确定性策略，**不做 LLM 识别**。策略依序尝试，首个命中返回：

```
显式技能 → 默认技能 → 唯一技能 → 首个技能
```

（实现：`app/runtime/resolver/skill_resolver.py`，各策略实现 `SkillStrategy` Protocol，
未来追加权限 / 上下文感知策略时追加进策略链即可，不改核心流程。）

- 输入：可用技能 ID 集合、默认技能、用户显式技能。
- 输出：选中的 skill_id；全不命中返回 `None`。
- 策略链只做「选技能」，不产上下文——上下文由 SkillAssembler 组装。

---

## 3. 装配计划契约（`AssemblyPlan`）

装配的唯一产物，运行时据此执行。跨层传递用 pydantic 模型：

| 字段 | 用途 |
|------|------|
| `agent_id` / `skill_id` | 本次装配的身份 |
| `system_prompt` | 已组装的系统消息（见 §4） |
| `required_mcp_servers` | 必需且启用的 MCP 服务，运行期任一启动失败 → 终止本轮 |
| `optional_mcp_servers` | 可选 MCP 服务 |
| `mcp_degrade_notes` | 可选服务名 → 降级说明文本 |
| `capabilities` | 能力装配计划列表（`CapabilityPlan`，见 §5） |
| `core_tool_names` | 技能声明的核心工具（进 Tier 1） |
| `scripts` | 技能脚本 + 门禁校验器脚本（进 Tier 1） |
| `env_whitelist` | 智能体环境变量白名单 |
| `model_preference` / `thinking_preference` | 模型与思考偏好，供运行时选择 |

描述符与暴露集合**不在**装配计划内——那是工具代理按 `core_tool_names` + MCP 工具列表构建的。

---

## 4. 系统提示组装

分节拼接，顺序固定：

```
# 智能体：<展示名> + 智能体正文（全局约束）
# 技能：<一句话职责> + 技能正文（完整工作流）
# 参考文档（按需读取）  → 路径：何时该读
# 模板                  → 路径：用途
# 门禁                  → id：通过条件
# 平台红线（强制）       → 硬约束段，任何技能都注入
```

平台红线段是平台硬约束，不可被技能正文覆盖：

- 涉及智能体身份时一律使用展示名（`display_name`）。
- 思考过程与可见回答中严禁出现内部 `agent_id` / 智能体标识字符串（包名、目录名、工具命名空间前缀等）。

---

## 5. 依赖与能力解析

### 5.1 MCP 依赖（点名服务，`mcp_dependencies`）

| 情况 | 行为 |
|------|------|
| 服务 `enabled: false` | 直接跳过装配，不视为错误（注册表「禁用 ≠ 注销」语义，占位条目），即使声明为必需 |
| 服务启用且必需 | 进 `required_mcp_servers` |
| 服务启用且可选 | 进 `optional_mcp_servers`，附 `degrade_note` |

### 5.2 能力依赖（`capability_dependencies`）

解析为 `CapabilityPlan`，运行时据此主备切换 / 降级：

| 字段 | 解析规则 |
|------|---------|
| `capability` | 须存在于注册表 `capabilities` 段，否则 `RegistryValidationError` |
| `strategy` | `failover`：按候选顺序主备切换，首个可用者生效；`all`：全部候选激活为独立工具，不做切换不做降级 |
| `candidate_servers` | 只取 `enabled: true` 的服务 |
| `fallback_capability` | 注册表声明的降级目标能力；目标未注册 → `RegistryValidationError` |
| `fallback_servers` | 降级目标能力中 `enabled: true` 的服务 |
| `core_tools` / `required` / `degrade_note` | 透传技能清单声明 |

**`strategy=all` 时忽略 `fallback`**——多提供方并存场景没有「主备」概念。

---

## 6. 门禁校验器注册

有校验器的门禁注册为脚本工具 `<agent>.<skill>.script.gate_<id>`，V2 中由
Contract 体系统一执行（ScriptGateExecutor 归一为 ContractExecutor，见
`react-runtime-v2-architecture.md` §14）。无校验器的门禁保持提示词自检（弱门禁）。

校验器脚本副作用一律标 `READ_ONLY`，不入注入清单之外的工具目录。

---

## 7. 降级决策汇总

| 情况 | 装配层动作 | 运行时动作 |
|------|-----------|-----------|
| 必需 MCP 服务 `enabled: false` | 跳过装配（不算错误） | — |
| 必需 MCP 服务启用但启动失败 | 正常产出计划 | 发错误事件并终止本轮 |
| 可选 MCP 服务不可用 | 记 `degrade_note` | 注入降级说明，继续 |
| 能力 failover：首候选不可用 | 计划携带全部候选 | 按顺序尝试，首个可用者生效，其余标记降级 |
| 能力 fallback：全部候选不可用 | 计划携带 `fallback_servers` | 降级到 fallback 能力，降级说明由系统生成（不来自技能清单） |

---

## 8. 自检清单

- [ ] 技能解析走确定性策略链，无 LLM 识别
- [ ] `AssemblyPlan` 为 pydantic 模型，跨层传递不序列化内部句柄
- [ ] 系统提示分节固定，平台红线段恒在末尾且不可覆盖
- [ ] 服务 `enabled: false` 时跳过装配，不报错
- [ ] 能力未注册 / fallback 目标未注册时抛 `RegistryValidationError`
- [ ] `strategy=all` 时未错误应用 fallback
- [ ] 门禁校验器注册为脚本工具且副作用为只读
- [ ] 装配层不启动 MCP、不暴露工具、不发事件（那是运行时）
