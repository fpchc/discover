# 智能体包契约规范

## 适用场景

- 新增或修改 AGENT / SKILL 清单
- 修改智能体注册、加载、校验、索引或热重载
- 判断脚本、Schema、参考文档和模板的归属

## 不适用场景

- 运行时如何执行装配计划
- MCP 传输、工具分发或 LLM 请求细节

## 职责边界与权威来源

本文件定义“智能体包允许声明什么”。清单加载后的装配行为见 `skill-assembly-spec.md`；当前实现路径以 `.ai/MODULE_MAP.md` 为准。

## 1. 目录契约

```text
agents/<agent-id>/
├── AGENT.md
└── <skill-id>/
    ├── SKILL.md
    ├── references/
    ├── scripts/
    ├── schemas/
    └── templates/
```

技能专属资源必须位于所属技能目录。多个智能体都需要的通用执行能力应上移为平台能力，禁止跨智能体目录引用。

## 2. 文件结构

AGENT.md 和 SKILL.md 均由两部分组成：

1. YAML frontmatter：供平台确定性解析和校验。
2. Markdown 正文：供运行时作为行为约束或工作流上下文装配。

结构化字段不得只写在正文；正文不得重复模拟已存在的 manifest 字段。

## 3. AgentManifest

| 字段 | 必需 | 约束 |
|---|:---:|---|
| `kind` | 否 | 固定为 `agent`，默认 `agent` |
| `type` | 否 | 当前固定为 `expert`，默认 `expert` |
| `agent_id` | 是 | kebab-case、等于目录名、全局唯一，且不得为保留字 `generic` |
| `display_name` | 是 | 用户可见名称 |
| `version` | 是 | 版本字符串 |
| `description` | 是 | 一句话职责 |
| `scope.applies` / `scope.does_not_apply` | 是 | 同时填写，明确边界 |
| `default_skill` | 否 | 必须存在于 `skills` |
| `model_preference` | 否 | 逻辑偏好或别名，不写真实密钥和地址 |
| `thinking_preference` | 否 | `off / low / medium / high` |
| `env_whitelist` | 否 | 脚本可见的环境变量名白名单 |
| `skills` | 是 | 非空，成员须与技能目录一致 |

Agent 正文只放跨技能长期一致的身份、语气、输出原则和通用禁令。它每轮常驻，必须显著短于 Skill 正文。

## 4. SkillManifest

| 字段 | 必需 | 约束 |
|---|:---:|---|
| `skill_id` | 是 | kebab-case、等于目录名、在智能体内唯一 |
| `version` / `description` | 是 | 版本与一句话职责 |
| `scope.applies` / `scope.does_not_apply` | 是 | 同时填写 |
| `keywords` | 否 | 仅用于预筛，不作为唯一判据 |
| `mcp_dependencies` | 否 | 仅声明不可互换的具体服务依赖 |
| `capability_dependencies` | 否 | 声明可由注册表解析的能力抽象 |
| `scripts` | 否 | 白名单脚本声明 |
| `documents` | 否 | 按需读取的参考文档 |
| `gates` | 否 | 可执行或提示词门禁 |
| `templates` | 否 | 模板路径与用途 |

Skill 正文只保留当前技能的语义工作流、执行纪律、降级要求和输出契约。可确定的流程跳转、预算、重试和校验应由 Runtime、配置或脚本承担。

## 5. 依赖声明

### MCP 服务依赖

`server` 必须存在于 MCP 注册表。`core_tools` 控制预暴露工具；`required` 默认 `true`；可选依赖可提供 `degrade_note`。

### 能力依赖

`capability` 必须存在于注册表 `capabilities`。可互换提供方一律通过能力声明，不在技能中绑定具体服务。能力的候选顺序、策略和 fallback 由注册表维护。

同一业务需求不得同时通过具体服务和等价能力重复声明。

## 6. 脚本、文档、门禁与模板

### 脚本

- `path` 必须位于当前技能 `scripts/`，禁止绝对路径和目录穿越。
- `name` 在技能内唯一；`description` 面向模型说明用途。
- 复杂输入必须声明 `schema_path`，且 Schema 位于 `schemas/`。
- 超时和副作用通过结构化字段声明；副作用默认只读。
- `history_store: true` 只用于平台注入历史、脚本纯计算的场景。

### 参考文档

- `path` 必须位于 `references/`；`when` 必须说明何时读取。
- 默认按需读取；只有短小且每次都必需的内容才允许 `preload: true`。

### 门禁

- `id` 在技能内唯一；`condition` 必须可判定。
- 可编码校验的门禁应提供 `validator` 和必要的 `schema_path`，不要只依赖提示词自检。
- `blocking` 明确失败是否阻断推进。

### 模板

模板必须位于当前技能目录，只声明路径和用途；不得从其他智能体复用文件路径。

## 7. 加载期校验

加载器必须 fail-fast 校验：

- ID 与目录名、保留字、非空技能索引和默认技能引用
- Agent / Skill 正文预算
- 注册表中的服务和能力引用
- 脚本名唯一、资源路径存在、路径未越界
- Schema、validator、文档和模板位于规定子目录
- 脚本中无绝对路径字面量

清单错误统一转换为可定位的注册校验异常，不允许静默跳过非法包。

## 8. 本规范专属检查

- [ ] frontmatter 与正文职责分离，无重复状态字段
- [ ] Agent 正文只放跨技能规则，Skill 正文不承担可确定流程控制
- [ ] 所有资源归属当前技能，路径相对且存在
- [ ] 可互换提供方使用 capability，而非绑定具体服务
- [ ] 可执行门禁已有 validator，脚本副作用已声明
