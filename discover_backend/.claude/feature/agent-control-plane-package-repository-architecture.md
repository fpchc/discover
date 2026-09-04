# Agent Control Plane + Skill Package Repository 完全重构方案

> **文档性质**：Agent/Skill/Prompt 管理、存储、发布与运行分发的目标架构  
> **创建日期**：2026-09-03  
> **状态**：设计方案，待确认后实施  
> **重构方式**：完全重构，不以兼容当前 `agents/` 目录结构为约束  
> **关联文档**：`react-runtime-v2-architecture.md`

## 1. 决策摘要

当前 `agents/{agent}/{skill}` 目录是验证 Demo 的静态加载源，不作为正式生产架构继续扩展。正式系统采用 **Agent Control Plane + Package Repository + Runtime Distribution** 三层模型：

```text
Control Plane
  管理 Agent / Skill / Prompt 的 Definition、Draft、Version、Evaluation、Release

Package Repository
  保存不可变包对象；PostgreSQL 保存元数据，Blob Store 保存包内容

Runtime Distribution
  解析 Deployment、校验 digest、物化只读缓存、生成 Runtime Snapshot

Agent Runtime V2
  固定 Snapshot 执行 Workflow + Bounded ReAct
```

核心决策：

1. Agent 与 Skill 解耦。Skill 是独立、可复用、可单独版本化的一级实体，不再由 Agent 目录物理拥有。
2. Prompt 是可编辑、可评测、可发布、可回滚的版本化资产，不再只是 Markdown 中不可追踪的正文。
3. Definition、Draft、Version、Deployment、Run Binding 分离建模。
4. 数据库保存生命周期和关系；Blob Store 保存不可变 Package Archive。
5. 首期使用本地 Package Store，但所有上层依赖抽象，后续可切换 S3。
6. Deployment 生成精确 Resolution Lock；运行中的 Run 固定 Deployment Snapshot。
7. Runtime 不直接扫描源码仓库中的 `agents/`，旧目录只允许一次性导入。
8. Declarative Package 与 Trusted Code Package 使用不同权限和发布门禁。
9. 发布新版本不修改旧版本；回滚创建新的 Deployment Revision，不篡改历史。

## 2. 为什么必须完全重构

### 2.1 当前目录承担过多生命周期

当前 `agents/` 同时承担 Agent 定义、Skill 定义、Prompt 编辑源、Reference、Schema、Script、Template、运行时加载源、发布产物和热重载监听目标。开发、管理、构建、发布和运行没有边界。

### 2.2 Skill 与 Agent 绑定

当前结构隐含“一个 Skill 只能属于一个 Agent”：

```text
agents/{agent}/{skill}
```

结果是 Skill 复用需要复制，Prompt/Schema/Script/Contract 容易分叉，修改半径扩大，无法独立评测或发布。

正式关系应为：

```text
Agent Definition ──引用──> Skill Release
Skill Definition ──独立存在，可被多个 Agent 引用
```

### 2.3 Prompt 修改与平台部署绑定

直接修改 `SKILL.md` 会让所有新 Run 立即读取新内容，缺少 Draft、Review、Evaluation、Publish、Rollback、A/B 和版本追踪。无法回答某个历史 Run 使用了哪版 Prompt，也无法安全进行提示词优化。

### 2.4 Runtime 依赖物理路径

Registry、装配和脚本执行依赖 `agents_root_dir`、`skill_dir` 和源码目录。这会导致多实例同步、更新非原子、内容完整性不可验证、无法切换对象存储，也无法让 Run 在发布变化后保持一致。

### 2.5 热重载不是发布系统

文件轮询只能解决开发便利，不能提供发布权限、验证、评测、灰度、回滚、多实例一致性或完整审计。生产应由 Release Revision 代替热重载。

### 2.6 脚本包等价于代码发布

当前宿主 subprocess 直跑模式下，允许普通用户上传带 Python 脚本的包，等价于授予远程代码执行能力。Prompt 编辑、声明式配置和可信脚本必须分开治理。

## 3. 目标与非目标

### 3.1 目标

- Agent、Skill、Prompt 成为独立领域实体；
- Skill 可跨 Agent 复用；
- Prompt 有 Draft、Version、Evaluation、Publish、Rollback 生命周期；
- 已发布内容不可变；
- 每个 Run 可重现使用的版本组合；
- Agent 内容变更不要求发布 FastAPI 平台代码；
- 首期支持本地 Package Store 和只读 Runtime Cache；
- 发布具有静态验证、Evaluation Gate 和审计；
- 带脚本包具有受信任发布边界；
- 与 Runtime V2 的 `AgentDecision`、`PhaseExecutionContract`、Contract 对接；
- 最终删除生产对 `agents/` 的依赖。

### 3.2 非目标

- 首期不实现公共技能市场；
- 首期不允许普通用户发布任意 Python 依赖；
- 首期不实现在线代码 IDE；
- 首期不要求 S3，但不阻塞后续切换；
- 不把所有包文件拆成数据库行；
- 不长期兼容旧目录加载器；
- 不允许运行中的 Run 自动切换新 Prompt；
- 不允许 LLM 修改已发布 Package。

## 4. 领域模型

### 4.1 Agent Definition

面向用户的角色和能力组合，负责展示信息、Persona、默认模型策略、可用 Skill 引用、默认 Skill、Agent 级预算上限、可见性和发布渠道。Agent 不复制 Skill 文件。

### 4.2 Skill Definition

独立可复用的执行能力，负责输入/输出契约、Workflow、Phase、工具依赖、Prompt、Contract、Schema、Reference、Template 和可选可信脚本。

### 4.3 Prompt Asset

带稳定 ID、作用域、模板、变量 Schema、版本、digest、Evaluation 结果和发布状态的模板资产。可属于 Agent、Skill、Phase、Contract repair 或 Finalize。平台安全 Prompt 由 Runtime 代码管理，不属于管理员可覆盖范围。

### 4.4 Draft

可变编辑态，可基于历史 Version 创建，但不能被生产 Runtime 使用。Draft 的任何修改都会使旧 Validation、Evaluation 和 Build Candidate 失效。

### 4.5 Component Version

不可变构建结果，包括 Agent Version、Skill Version、Prompt Version、Workflow Version 和 Contract Version。任何内容变化都创建新 Version。

### 4.6 Deployment

环境中实际生效的完整组合：

```text
Agent Version
+ exact Skill Versions
+ exact Prompt Versions
+ Workflow/Contract Versions
+ Tool Requirements
+ Package Digests
= Deployment Snapshot
```

### 4.7 Run Binding

Run 创建时固定 deployment ID、revision、Resolution Lock digest、Agent/Skill/Prompt/Workflow 版本和 Materialized Bundle digest。后续发布、clarification、重试和恢复均不得改变该绑定。

## 5. 总体架构

```text
┌─────────────────────────────────────────────────────┐
│ Management Interfaces                               │
│ Admin API / CLI / Future UI                         │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│ Agent Control Plane                                 │
│ Definition / Draft / Validation / Evaluation        │
│ Build / Release / Rollback / Audit                  │
└─────────────┬──────────────────────┬────────────────┘
              │                      │
┌─────────────▼────────────┐  ┌──────▼────────────────┐
│ PostgreSQL Metadata     │  │ Package Repository    │
│ relation/lifecycle/lock │  │ Local Blob first      │
└─────────────┬────────────┘  └──────┬────────────────┘
              └──────────────┬───────┘
                             │
┌────────────────────────────▼────────────────────────┐
│ Build & Distribution                                │
│ validate → evaluate → build → digest → lock → release│
└────────────────────────────┬────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────┐
│ Runtime Package Resolver                            │
│ resolve → fetch → verify → materialize → compile   │
└────────────────────────────┬────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────┐
│ Immutable Local Runtime Cache                       │
│ content-addressed / read-only / atomic              │
└────────────────────────────┬────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────┐
│ Agent Runtime V2                                    │
│ Workflow + Bounded ReAct + Policy + Contract        │
└─────────────────────────────────────────────────────┘
```

## 6. Agent 与 Skill 解耦

### 6.1 组合关系

```text
Agent A ─┬─ Skill X v3
         ├─ Skill Y v1
         └─ Skill Z v5

Agent B ─┬─ Skill X v3
         └─ Skill Q v2
```

Skill X 只有一份 Version，可被多个 Agent Deployment 引用。

### 6.2 Agent Composition

Agent Draft 声明：

- Skill ID；
- Authoring 阶段允许的版本范围；
- 默认 Skill；
- 展示名称覆盖；
- Agent 级预算收紧；
- Agent 级工具收紧；
- Skill Input 预设；
- 可见性。

Deployment Build 把范围解析成精确 Version 并写入 Resolution Lock。

### 6.3 显式引用

不再通过“发现 Agent 目录下的子目录”识别 Skill。所有关联必须显式声明，避免目录移动或临时文件改变运行行为。

### 6.4 Skill 的 Agent 无关性

可复用 Skill：

- 不硬编码 Agent ID；
- 不依赖父目录名；
- 不读取 Agent 私有文件；
- 通过 Phase Input 接收 Agent 预设；
- 通过 Prompt Compiler 组合 Agent Persona；
- 通过 Deployment 限制哪些 Agent 可引用。

业务上独占的 Skill 用权限和可见性约束，不用物理嵌套实现。

## 7. Prompt 架构

### 7.1 固定编译层次

```text
Platform Safety Prompt
+ Runtime Control Protocol
+ Agent Persona Prompt
+ Skill Instruction Prompt
+ Current Phase Prompt
+ Contract/Repair Prompt（按需）
+ Run Dynamic Context
```

### 7.2 Platform Prompt

由 Runtime 代码版本管理，负责控制工具协议、不伪造 Observation、不绕过 Workflow、工具授权、数据安全等规则，Agent 管理员不能覆盖。

### 7.3 Agent Persona Prompt

只描述稳定身份、专业领域、通用原则、表达风格和跨 Skill 风险边界，不承载具体 Phase 流程。

### 7.4 Skill Prompt

描述 Skill 目标、业务方法、分析原则、工具使用指导、质量要求和禁忌，不拥有切换 Phase 的权力。

### 7.5 Phase Prompt

只描述当前阶段：目标、Phase Input、允许工具、候选输出 Schema、完成条件、剩余预算、控制工具、Contract failures。

### 7.6 Repair Prompt

Contract 失败时仅注入候选输出、确定性失败项、剩余 repair budget、可修复字段和禁止重放的副作用 Action，避免重新加载无关完整历史。

### 7.7 Finalization Prompt

明确已完成/未完成阶段、limitations、degraded sources、artifacts、termination reason 和 Finalization Reserve。

### 7.8 Prompt Template 契约

每个模板具有：

- `prompt_id`；
- `scope`；
- `template_version`；
- `variables_schema`；
- `content_digest`；
- `output_intent`；
- `evaluation_suite`；
- `owner`。

变量必须显式声明，不得让模板隐式读取整个 RunState。

### 7.9 Prompt 编译审计

每次 LLM Call 记录 Deployment、Agent/Skill/Phase Prompt Version、各层 digest、rendered digest、variables digest、provider/model 和 Evaluation lineage。默认不要求日志保存完整敏感 Prompt 明文，但必须可由版本和输入重建。

## 8. Package 类型和格式

### 8.1 Agent Package

```text
agent-package/
├── package.yaml
├── agent.yaml
├── prompts/
│   └── persona.md
├── assets/
└── README.md
```

只包含 Agent Manifest、Persona、Skill 依赖声明、模型/预算策略和展示资产，不复制 Skill 内容。

### 8.2 Skill Package

```text
skill-package/
├── package.yaml
├── skill.yaml
├── workflow.yaml
├── prompts/
│   ├── skill.md
│   ├── phases/
│   ├── repair.md
│   └── finalize.md
├── schemas/
├── contracts/
├── references/
├── templates/
├── scripts/
└── tests/
    └── golden-cases.yaml
```

### 8.3 Prompt Package 决策

首期 Prompt 作为所属 Agent/Skill Package 的版本化资产，同时在数据库单独索引 Prompt Version。只有确认存在跨 Skill 大规模复用需求后才拆独立 Prompt Package，避免首期过度拆分。

### 8.4 Declarative Package

仅含 YAML/JSON、Markdown、Schema、Reference、Template 和已注册工具引用，不含可执行代码，属于普通管理发布范围。

### 8.5 Trusted Code Package

包含 Python 脚本或其他可执行资源，Manifest 必须声明 trust level、script entries、side effects、环境变量白名单、timeout、依赖政策和 reviewer，只允许 Trusted Publisher 发布。

### 8.6 Manifest 是身份来源

Package ID、kind、version、schema version、entry、dependencies 和 inventory 来自 Manifest，不来自目录名。所有引用必须位于 Package 根内。

## 9. 生命周期

### 9.1 Definition

```text
ACTIVE → DISABLED → ARCHIVED
```

Definition 是逻辑身份，不因每次 Prompt 修改创建新 Definition。

### 9.2 Draft

```text
EDITING
  → VALIDATING
  → INVALID | VALID
  → EVALUATING
  → EVALUATION_FAILED | READY_TO_BUILD
```

Draft 可变，任何修改使旧验证、Evaluation 和 Build Candidate 失效。

### 9.3 Version

```text
BUILT → VERIFIED → DEPRECATED → ARCHIVED
```

Version 不可修改。发现问题只能创建新版本、标记 Deprecated 或回滚 Deployment。

### 9.4 Deployment

```text
DRAFT → VALIDATED → PUBLISHED → SUPERSEDED | ROLLED_BACK
```

同一 Agent、环境和 Channel 只有一个 Active Deployment。发布前 Package 已构建完成，发布事务只切换不可变对象引用。

### 9.5 回滚

回滚创建新 Revision 指向历史组合：

```text
revision 10 → version 5
revision 11 → version 6
revision 12 rollback → version 5
```

不得覆盖或改写历史 Revision。

## 10. Resolution Lock

Authoring 阶段可以声明版本范围，Deployment 不允许浮动依赖。Build/Release 生成：

```text
resolution.lock
- agent_version_id
- exact skill_version_ids
- exact package digests
- exact prompt versions
- exact workflow/contract versions
- tool requirement revisions
- compiler version
- lock digest
```

Runtime 禁止解析 `latest`、兼容最新版或目录第一个。RunState 固定 Deployment Revision、Lock Digest 和 Bundle Digest，clarification、Checkpoint 恢复和重试继续使用原 Lock。

## 11. 元数据存储

PostgreSQL 保存生命周期、关系、状态和审计；大文件树保存在 Blob Store。

### 11.1 核心表

#### agent_definitions

逻辑 Agent：ID、agent key、展示信息、owner、visibility、status、时间。

#### skill_definitions

逻辑 Skill：ID、skill key、展示信息、owner、visibility、status、时间。

#### component_drafts

component kind、definition ID、base version、revision、source blob、status、validation digest、updated by/time。

#### package_objects

package kind、blob ID、SHA-256、大小、Manifest schema、trust level、创建时间。

#### component_versions

component kind、definition ID、semantic version、package object、content digest、draft lineage、status、actor/time。

#### prompt_versions

owner component version、prompt key、scope、template digest、variables schema digest、Evaluation status。

#### agent_deployments

Agent Definition、environment、channel、revision、Agent Version、Resolution Lock blob/digest、status、publisher/time。

#### evaluation_runs

target/version、suite version、status、case/passed count、quality score、Token、duration、result blob。

#### agent_management_audit_logs

actor、action、target、before/after revision、metadata、created time。

### 11.2 一致性约束

- Definition key 全局或租户内唯一；
- semantic version 在同一 Definition 下唯一；
- Package digest 唯一并可去重；
- Active Deployment 用唯一约束保证单一生效；
- Draft revision 乐观锁；
- 已被 Version、Deployment、Run 引用的 Package Object 不得删除；
- 发布事务不修改不可变 Version。

## 12. Package Repository 与本地存储

### 12.1 抽象接口

按 ISP 拆分小型 Protocol：

- PackageObjectReader：读取、存在性；
- PackageObjectWriter：写入不可变对象；
- PackageObjectCleaner：清理无引用对象；
- PackageMaterializer：物化 digest；
- DeploymentResolver：解析 Deployment。

Runtime 不依赖 LocalStorage 具体实现。

### 12.2 首期实现

复用现有 `BaseStorage` 的 Blob 能力，增加 Agent Package Repository 元数据与内容 digest。路径、大小、文件数、缓存期限和 Manifest 版本均进入 Settings。

### 12.3 内容寻址

```text
storage/agent-packages/objects/sha256/ab/cd/{full_digest}.zip
```

相同内容只保存一次。ZIP 只是运输格式，执行前必须安全物化。

### 12.4 三类目录严格分离

#### Authoring Workspace

```text
agent-authoring/{draft_id}/
```

可变编辑、预览、验证和 Evaluation，不得被生产 Runtime 读取。

#### Package Repository

```text
storage/agent-packages/objects/sha256/...
```

不可变权威对象，只能通过 Build 写入。

#### Runtime Cache

```text
agent-package-cache/
├── agent/{definition_id}/{version}/{digest}/
├── skill/{definition_id}/{version}/{digest}/
└── bundles/{deployment_id}/{revision}/{lock_digest}/
```

只读、内容寻址、可删除重建，不是事实来源。

## 13. Package Build

Build 是从 Draft 到不可变 Version 的唯一通道：

```text
Load Draft
→ Validate Paths
→ Parse Manifests
→ Validate Schemas
→ Compile Workflow
→ Compile Prompts
→ Resolve Dependencies
→ Validate Tools/Contracts
→ Security Scan
→ Create Inventory
→ Archive
→ Compute Digest
→ Store Blob
→ Create Immutable Version
```

### 13.1 Inventory

记录 relative path、size、sha256、media type、execution flag 和 logical role。Runtime 物化后重新计算核对。

### 13.2 可重复构建

相同 Draft 内容、Builder Version 和 Dependency Lock 应产生相同 digest。随机时间戳不得写入影响 digest 的 Archive 内容，构建时间只存数据库元数据。

## 14. 静态验证

### 14.1 Manifest

检查 Schema Version、ID/Version、entry、package kind、trust level、文件引用和依赖环。

### 14.2 Prompt

检查变量全部声明、无未绑定变量、不读取整个 RunState、控制工具名称正确、不伪造 Observation、Phase ID 对齐和大小限制。

### 14.3 Workflow

检查 START/END 可达、Phase 唯一、条件边穷尽、input binding 有效、output schema/Contract 存在、无无预算循环、clarification/finalization 路径明确。

### 14.4 Tool

检查 Tool Catalog 可解析、required/optional、Side Effect Type、trust 权限、保留控制工具冲突和 Phase 白名单。

### 14.5 Contract

检查 Schema 匹配、repair 最大次数、fallback 合法、FAIL/WARN/PARTIAL 语义和脚本 trust level。

## 15. Evaluation 与 Prompt 优化

提示词优化必须进入可重复 Evaluation，不允许凭人工感受直接覆盖生产文件。

### 15.1 Evaluation Suite

每个 Skill 至少维护：

- normal cases；
- clarification cases；
- tool selection cases；
- phase completion cases；
- Contract repair cases；
- no-progress cases；
- degraded/partial cases；
- Prompt Injection cases。

### 15.2 Evaluation 输入

Package Version、Prompt Version、Provider/Model、Runtime Version、Tool Fixture Version、Golden Case Suite Version 和独立预算全部固定。

### 15.3 Evaluation 输出

- Case pass/fail；
- Contract score；
- Tool selection accuracy；
- completion decision accuracy；
- clarification precision；
- no-progress termination；
- Token/Latency；
- artifacts；
- regression diff；
- sanitized trace。

### 15.4 发布门禁

Declarative Package 发布至少要求：

- 静态验证通过；
- Required Cases 全部通过；
- 质量分不低于配置阈值；
- 无高危 Prompt Injection 失败；
- Token/Latency 在阈值内；
- 无未解释的新回归。

### 15.5 Candidate/Baseline 对比

展示成功率、质量、Token、Latency 的差值，以及新增失败和已修复用例。Draft 修改后旧 Evaluation 标记为 stale。

### 15.6 Evaluation 隔离

使用隔离工作区、Fake/Mock Tool 或测试数据源；不连接生产数据库，不执行不可逆外部写调用。

## 16. Prompt 发布流程

```text
Create Draft from Active Version
→ Edit Prompt/Workflow/Contract
→ Static Validate
→ Run Evaluation
→ Review Diff
→ Build Immutable Version
→ Create Deployment Candidate
→ Resolve Exact Dependencies
→ Publish Deployment Revision
→ Observe Metrics
→ Promote or Rollback
```

Hotfix 也必须创建新 Version 和 Revision，不允许覆盖 Active Package。可以缩短 Suite，但安全协议和结构化决策用例不能跳过。

## 17. Runtime Distribution

### 17.1 DeploymentResolver

Run 创建时：

1. 按 Agent ID、环境和 Channel 解析 Active Deployment；
2. 读取并校验 Resolution Lock；
3. 检查 Package Objects；
4. 读取或生成 Materialized Bundle；
5. 将绑定写入 RunState。

### 17.2 PackageMaterializer

负责获取 Archive、校验 digest、安全解压、核对 Inventory、加载类型化定义、写入内容寻址 Cache 和原子切换最终目录。

```text
download temp archive
→ verify digest
→ extract temp directory
→ validate inventory
→ compile snapshot
→ atomic rename to final cache
```

Runtime 不读取临时目录。

### 17.3 Runtime Snapshot

只读 Snapshot 包含 Agent Definition、Skill Definition、Workflow、Prompt Templates、Schema、Contract、Tool Requirements、Script Entries、Package Roots 和全部 digests。Runtime V2 只消费 Snapshot，不感知 ZIP、数据库或 Repository。

### 17.4 Cache 一致性

Cache Key 包含 digest，不覆盖旧目录。新 Run 使用新 Deployment，旧 Run 继续引用旧 Cache；活跃引用归零后才允许清理。Cache 丢失时按 digest 重建。

## 18. 与 Runtime V2 的接缝

### 18.1 Run 创建

```text
agent_id
→ DeploymentResolver
→ Deployment Snapshot
→ Skill Selection
→ PhaseExecutionContract
→ Runtime V2 RunState
```

### 18.2 结构化决策通道

Package 中的 Prompt 必须遵守 Runtime V2 保留控制工具：

- `complete_phase`；
- `submit_final_answer`；
- `request_clarification`。

Schema 由 Runtime 提供，Package 只声明协议版本，不得自定义不兼容结构。

### 18.3 Phase 接缝

Skill Workflow 必须编译为 PhaseExecutionRequest、PhaseExecutionOutcome、PhaseOutput、input bindings 和 Contract transitions。Package 格式不能反向决定 Runtime Core 模型。

### 18.4 Prompt 编译

Runtime 使用 Snapshot 模板和 Run 数据组装 Context。Package 不能直接生成完整 ChatRequest，也不能覆盖 Platform Prompt。

### 18.5 Tool 与 Contract

Package 只声明 Tool Requirement 和业务 Contract。Runtime 负责 Tool Catalog 解析、授权、执行、预算和通用 Contract 状态转移。

## 19. 管理服务

### AgentDefinitionService

创建/修改 Agent 元数据、可见性、启停和 Deployment 查询。

### SkillDefinitionService

创建/修改 Skill、复用权限、消费者查询和禁用新引用。

### DraftService

从空模板或历史 Version 创建 Draft、乐观锁保存、导入导出和 Source Blob 管理。

### ValidationService

协调 Manifest、Prompt、Workflow、Schema、Contract、Tool、Security 和 Dependency 验证。

### EvaluationService

运行隔离评测、聚合指标、生成 Candidate/Baseline Diff 和发布门禁结果。

### BuildService

锁定 Draft Revision、生成 Archive/Inventory/Digest、保存 Package Object、创建不可变 Version。

### ReleaseService

解析依赖、生成 Lock、校验发布 Gate、原子创建 Deployment Revision、通知运行节点。

### RollbackService

选择历史 Deployment、确认 Package 可用、创建新回滚 Revision 并记录审计。

## 20. 管理 API 与 CLI

### Agent

```text
POST   /admin/agent-definitions
GET    /admin/agent-definitions
GET    /admin/agent-definitions/{agent_id}
PATCH  /admin/agent-definitions/{agent_id}
POST   /admin/agent-definitions/{agent_id}/disable
```

### Skill

```text
POST   /admin/skill-definitions
GET    /admin/skill-definitions
GET    /admin/skill-definitions/{skill_id}
PATCH  /admin/skill-definitions/{skill_id}
GET    /admin/skill-definitions/{skill_id}/consumers
```

### Draft/Evaluation

```text
POST   /admin/component-drafts
GET    /admin/component-drafts/{draft_id}
PUT    /admin/component-drafts/{draft_id}/source
POST   /admin/component-drafts/{draft_id}/validate
POST   /admin/component-drafts/{draft_id}/evaluations
GET    /admin/evaluations/{evaluation_id}
GET    /admin/evaluations/{evaluation_id}/diff
```

### Build/Release

```text
POST   /admin/component-drafts/{draft_id}/build
GET    /admin/component-versions/{version_id}
POST   /admin/agent-definitions/{agent_id}/deployment-candidates
POST   /admin/agent-deployments/{deployment_id}/publish
POST   /admin/agent-definitions/{agent_id}/rollback
GET    /admin/agent-definitions/{agent_id}/deployments
```

首期管理 UI 前先实现 `agentctl import|validate|evaluate|build|publish|rollback|export`。CLI 调用相同 Service，不复制业务逻辑。

## 21. 权限、审计与安全

### 21.1 角色

| 角色 | 权限 |
|---|---|
| Viewer | 查看 Definition、Version、Deployment |
| Editor | 编辑 Declarative Draft |
| Evaluator | 执行和查看 Evaluation |
| Publisher | 发布 Declarative Package |
| Trusted Publisher | 发布 Trusted Code Package |
| Administrator | 权限、归档和紧急回滚 |

编辑与发布分离。Publisher 不能绕过 Validation/Evaluation；超级用户紧急发布必须记录 bypass reason。所有写操作关联 account ID，敏感 Prompt 不直接写日志，仅保存 ID、digest 和差异摘要。

### 21.2 Declarative 与 Trusted Code

#### Declarative Package

可包含 Prompt、Workflow、Schema、Reference、Template 和已注册工具引用，可由普通 Editor 编辑，发布前必须经过静态验证与 Evaluation。

#### Trusted Code Package

包含脚本或其他可执行资源，只允许 Trusted Publisher。必须具备 reviewer、代码 digest、环境变量白名单、工作目录限制、超时、输出上限、依赖政策和静态扫描。当前宿主 subprocess 模式下不开放普通用户在线创建脚本。

### 21.3 Archive 安全

物化时拒绝：

- `../` 路径穿越；
- 绝对路径和 Windows drive path；
- 指向包外的符号链接；
- 重复覆盖文件；
- ZIP bomb；
- 超过文件数/解压大小限制；
- Manifest 未列出的可执行文件。

### 21.4 Tool 权限

Package 声明 Tool ID 不等于获得权限。实际工具集合是：

```text
平台允许
∩ Deployment 允许
∩ Skill 需要
∩ 当前 Phase 允许
∩ 当前账号权限允许
```

## 22. 本地存储与多实例

### 22.1 单实例

Local Blob Store 和 Runtime Cache 可以位于同一台机器，但逻辑上分开：

- Blob Store 是权威对象存储；
- PostgreSQL 是元数据事实来源；
- Cache 是可重建派生数据。

### 22.2 多实例

多实例使用共享文件卷或切换 S3。发布后可通过 Redis Pub/Sub、DB revision 轮询或内部事件通知节点。通知只用于刷新，不是事实来源；Run 创建时仍需读取并校验 Active Deployment。

### 22.3 垃圾回收

Package Object 只有在无 Version、Deployment、Run/Checkpoint 引用、超过保留期且不在审计冻结范围时才可删除。Cache 清理不影响权威对象。

## 23. 建议代码结构

```text
app/domain/agent_management/
├── models.py              # Definition/Draft/Version/Deployment
├── protocols.py           # 管理边界 Protocol
├── service.py             # 管理用例编排
├── validation.py
├── build.py
├── release.py
└── evaluation.py

app/capabilities/agent_packages/
├── archive.py             # ZIP inventory/digest
├── materializer.py        # 安全解压、原子缓存
├── loader.py              # Package → Snapshot
├── compiler.py            # Prompt/Workflow 编译
└── resolver.py            # Deployment → Bundle

app/infrastructure/agent_repository/
├── metadata.py            # SQLAlchemy metadata store
├── package_store.py       # BaseStorage-backed object store
├── cache.py
└── notifications.py

app/interfaces/http/agent_management.py
app/interfaces/schemas/agent_management.py
app/cli/agentctl.py
```

依赖方向：

```text
interfaces/cli
  → domain/agent_management
  → capabilities/agent_packages abstractions
  → infrastructure implementations
```

Runtime V2 只依赖 Runtime Bundle Resolver Protocol，不直接依赖管理 Service、SQLAlchemy 或 LocalStorage。

## 24. 完全重构迁移路线

本方案不把旧目录兼容层作为目标架构的一部分，只提供一次性 Importer。

### Phase 0：冻结旧目录

- 禁止新增旧格式特性；
- 为每个现有 Agent/Skill 记录 digest；
- 固化 Golden Cases；
- 导出 Prompt、工具、Schema、Script、Reference、Template 清单；
- 当前 Loader/HotReload 仅维持必要 Demo 行为。

### Phase 1：新领域模型与数据库

建立 Definition、Draft、Package Object、Component Version、Prompt Version、Deployment、Evaluation 和 Audit 模型，完成 Alembic 迁移及领域单测。

### Phase 2：Local Package Repository

实现 Blob-backed Package Store、Archive/Inventory/Digest、Materializer、Immutable Cache、安全校验、引用保护和垃圾回收。

### Phase 3：Build、Validation、Evaluation

实现 Prompt/Workflow 编译、静态验证、Golden Case Runner、Candidate/Baseline Diff 和不可变 Version 构建。

### Phase 4：Release 与 Runtime Resolver

实现 Resolution Lock、Deployment 原子发布、Run Version Pinning、Bundle Snapshot 和回滚。

### Phase 5：一次性导入 `agents/`

```text
旧 AGENT.md
  → Agent Definition + Persona Prompt Draft

旧 {agent}/{skill}/SKILL.md
  → 独立 Skill Definition + Skill Prompt Draft

旧 schemas/references/templates/scripts
  → Skill Package Draft Assets
```

Importer 不静默修补，必须报告重复 Skill、Agent 硬编码、绝对路径、缺 Schema Script、Prompt/业务说明混合、无法识别 Workflow 和保留工具冲突。每个导入对象经过人工确认、Evaluation、Build 和 Publish。

### Phase 6：切换 Runtime V2

Runtime 只通过 DeploymentResolver 加载；`/assistants` 读取 Active Deployment；Run 写入 Deployment/Lock；关闭旧文件扫描和生产 HotReloader；`agents_root_dir` 不再作为生产来源。

### Phase 7：删除旧目录

删除仓库 `agents/`、旧 Loader/Parser、旧 HotReload 配置和路径映射。保留迁移 Archive 与审计记录，并更新 `.ai/ARCHITECTURE.md`、`.ai/MODULE_MAP.md`。

### Phase 8：管理 UI 与远程存储

实现 Draft Prompt Editor、Workflow/Contract 视图、Evaluation Diff、Publish/Rollback、S3 Store 和灰度 Channel。

## 25. 验收标准

### 25.1 Agent/Skill 解耦

- [ ] Skill 是独立 Definition，不依赖 Agent 父目录；
- [ ] 同一 Skill Version 可被多个 Agent Deployment 引用；
- [ ] 修改 Agent Persona 不复制 Skill；
- [ ] 修改 Skill 产生独立 Skill Version；
- [ ] Deployment Lock 固定精确 Skill Version。

### 25.2 Prompt 生命周期

- [ ] Prompt 有稳定 ID、Version、digest；
- [ ] Draft 修改不影响生产；
- [ ] 发布前通过静态验证和 Evaluation；
- [ ] Run 可追踪 Prompt Version；
- [ ] 新 Prompt 不影响进行中的 Run；
- [ ] 可原子回滚 Prompt/Skill 组合。

### 25.3 Package Repository

- [ ] Archive 不可变并按 digest 校验；
- [ ] 数据库只保存元数据和 Blob 引用；
- [ ] Runtime 不读取 Authoring Workspace；
- [ ] Cache 删除后可以重建；
- [ ] 发布不覆盖旧 Package；
- [ ] 路径穿越、符号链接和 ZIP bomb 被拒绝。

### 25.4 Runtime 绑定

- [ ] Run 固定 Deployment Revision、Lock Digest 和 Bundle Digest；
- [ ] clarification、Checkpoint 恢复继续使用原版本；
- [ ] Runtime 不使用 latest 或浮动版本；
- [ ] 多实例解析同一 Deployment 得到相同 Bundle Digest；
- [ ] Runtime V2 只消费类型化 Snapshot。

### 25.5 发布与安全

- [ ] Build 是创建 Version 的唯一入口；
- [ ] Version 发布后不可修改；
- [ ] 回滚创建新 Revision；
- [ ] 发布者、Evaluation、变更原因和 reviewer 可审计；
- [ ] Declarative 与 Trusted Code 权限分离；
- [ ] 普通 Editor 不能发布脚本；
- [ ] Evaluation 不执行真实不可逆外部调用。

### 25.6 完全重构完成

- [ ] 生产 Runtime 不扫描 `agents/`；
- [ ] `agents_root_dir` 不再是生产配置；
- [ ] HotReloader 不承担发布职责；
- [ ] 旧 AgentRegistry 文件源删除；
- [ ] 旧 Agent 内容全部导入、归档或明确废弃；
- [ ] 仓库删除旧 `agents/`；
- [ ] 架构记忆已更新。

## 26. 测试策略

### 26.1 单元测试

- Manifest/Package Schema；
- Prompt variables 和编译顺序；
- Workflow compile；
- Dependency resolution 和 Lock；
- Inventory/Digest；
- Archive security；
- Draft optimistic lock；
- Release 状态机；
- 权限策略。

### 26.2 集成测试

- Build → Blob → Version；
- Publish → Active Deployment；
- Runtime Resolve → Materialize → Snapshot；
- Cache miss 重建；
- Rollback；
- 两 Agent 复用一个 Skill；
- 发布新 Skill 时旧 Run 保持旧版本；
- 多实例 Deployment revision 一致；
- Package GC 引用保护。

### 26.3 Evaluation 测试

- 正确使用控制工具；
- Phase completion；
- clarification；
- Contract repair；
- no-progress；
- partial finalization；
- Prompt Injection；
- Candidate/Baseline regression。

### 26.4 安全测试

- ZIP Slip；
- 绝对路径；
- Symlink escape；
- ZIP bomb；
- 超大文件数；
- Inventory 不一致；
- 非可信用户发布脚本；
- 非白名单环境变量；
- 删除被 Run 引用的 Package。

### 26.5 迁移测试

- 每个现有 Agent/Skill 可被 Importer 解析；
- 重复或非法内容给出明确报告；
- 导入前后 Golden Case 可比较；
- 切换后删除旧目录不影响 Runtime。

## 27. 观测指标

### 管理指标

- Draft 数量和平均存活时间；
- Validation 失败类型；
- Evaluation 通过率；
- Build 成功率；
- 发布频率和回滚率；
- Prompt 版本平均寿命。

### Runtime 指标

- Deployment resolve latency；
- Materialization latency；
- Cache hit rate；
- Digest mismatch；
- Bundle compile failure；
- 按 Deployment/Prompt Version 的成功、部分、失败率；
- Token、Latency、Contract score。

### 安全指标

- 非法 Archive 拒绝数；
- Trusted Code 发布数；
- Publish bypass 数；
- 未授权 Tool 声明数；
- Materialization security failure。

## 28. 明确拒绝的方案

### 28.1 继续扩展仓库 `agents/`

仍然绑定代码部署，缺少版本锁、发布、评测和审计。

### 28.2 管理页面直接修改生产目录

缺少不可变版本、原子发布和 Run 一致性，并形成远程文件编辑风险。

### 28.3 所有内容存数据库文本列

目录资产、模板、Schema 和脚本难维护、难导入导出、难构建校验。

### 28.4 Runtime 每次读取当前最新版

破坏 Run 重现、恢复、审计和在途一致性。

### 28.5 Agent Package 复制所有 Skill

继续制造重复、分叉和修改半径扩散。

### 28.6 热重载等同发布

无法解决权限、验证、Evaluation、灰度、回滚和多实例一致性。

### 28.7 普通 Prompt Editor 上传脚本

在宿主 subprocess 模式下等价于远程代码执行。

### 28.8 长期维护双加载器

形成两个事实来源，所有功能都需测试两套路径。旧目录仅允许一次性 Import。

## 29. 最终目标状态

```text
Agent 是用户可见角色和 Skill 组合；
Skill 是可独立复用、独立版本化的执行能力；
Prompt 是可评测、可发布、可回滚的版本化资产；
Draft 是唯一可变编辑态；
Version 是不可变构建产物；
Deployment 是环境中的原子生效快照；
Resolution Lock 固定全部依赖；
Package Repository 保存权威内容对象；
Local Cache 只保存可重建运行副本；
Run 固定 Deployment，不随发布漂移；
Runtime V2 只执行类型化 Snapshot，不感知源码目录；
带脚本 Package 通过受信任代码发布流程进入运行环境。
```

生产链路从：

```text
修改 agents/SKILL.md
→ 重启后端
→ Runtime 直接读取变化文件
```

替换为：

```text
创建 Draft
→ 优化 Prompt/Workflow
→ 静态验证
→ Golden Case Evaluation
→ Build Immutable Version
→ Resolve Exact Dependencies
→ Publish Deployment Revision
→ Runtime Materialize Snapshot
→ New Run Pin Version
→ Observe / Rollback
```

Control Plane 决定“生产执行哪个不可变版本”，Runtime Plane 负责“如何可靠执行该版本”。两者与 `react-runtime-v2-architecture.md` 共同构成正式 Agent 平台目标架构。

---

**文档结束**
