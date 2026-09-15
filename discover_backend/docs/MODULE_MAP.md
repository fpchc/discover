# 模块地图（职责 → 文件路径）

> 新增 / 删除模块文件后必须同步更新本表。
> 当前结构（2026-09-12 二次定稿）：**核心边界 `LLM + Harness + Environment = Agent System`
> 是三根顶层一等包**，DDD（`domain` / `application` / `infrastructure`）只承载业务 CRUD，
> 另有 `interfaces`（协议适配）、`bootstrap`（组合根）、`config` / `shared`（跨层）。

## 边界与依赖方向

```
llm/          L —— 模型接入：请求/分片词汇 + 提供方协议适配
harness/      H —— 驱动循环：用 LLM 与环境把一次任务跑完
environment/  E —— 智能体可感知 / 可操作的世界（工具、MCP、上下文、工作区、存储）

domain/ application/ infrastructure/   ← DDD：仅承载业务 CRUD（会话 / 文件 / 身份）
interfaces/                            对外协议（HTTP / SSE / 中间件）
bootstrap/ config/ shared/             组合根与跨层
```

| 层 | 允许依赖 | 硬约束 |
|---|---|---|
| `llm` | llm / config / shared | 不依赖 harness、environment、DDD、interfaces |
| `environment` | environment / llm / infrastructure / config / shared | 不依赖 harness、DDD、interfaces |
| `harness` | harness / llm / environment / config / shared | 不依赖 DDD、interfaces（`H = L + E` 单向） |
| `domain` | domain / config / shared | **零框架、零 I/O**（禁 fastapi / sqlalchemy / httpx / redis / anyio / langgraph） |
| `application` | application / domain / llm / harness / environment / infrastructure / config / shared | 业务用例可驱动三支柱；反向不成立 |
| `infrastructure` | infrastructure / domain / config / shared | 共享技术底座（DB / Redis / crypto / logging），不得依赖任何上层 |
| `interfaces` | 除 bootstrap 外全部 | 只做协议适配，不实现业务规则 |
| `bootstrap` | 全部 | 只组装，不承载业务判断 |

依赖方向由 `tests/unit/test_layering.py` 用 AST 断言守卫。

## 组合根（bootstrap）

| 职责 | 路径 |
|------|------|
| 应用组装工厂（create_app：中间件 + 路由挂载 + 生命周期） | `app/bootstrap/application.py` |
| 服务容器构造与启停顺序（start_services / stop_services，唯一装配点） | `app/bootstrap/container.py` |
| 扩展加载器（EXTENSIONS 有序元组 + initialize/startup/shutdown） | `app/bootstrap/extensions.py` |
| 进程入口（uvicorn 启动，host/port 配置驱动） | `app/main.py` |

## L —— 模型接入（`app/llm`）

| 职责 | 路径 |
|------|------|
| LLM 请求侧模型（ChatMessage / ChatRequest / ChatToolSpec / ToolFunction） | `app/llm/models.py` |
| 流式语义单元（SemanticChunk 家族 + ToolCall + 判别联合） | `app/llm/chunks.py` |
| LLM 客户端（httpx 流式，OpenAI 兼容协议，禁用 SDK） | `app/llm/client.py` |
| 提供方注册表 + 别名解析 + 密钥解析 | `app/llm/providers.py` |
| 流式分块解析（提供方载荷 → 语义分片，防腐层） | `app/llm/stream_parser.py` |
| 传输异常分类（httpx → 领域异常，只分类不重试） | `app/llm/errors.py` |
| 回合用量聚合（UsageAggregator：缓存命中 / 写入归一） | `app/llm/usage.py` |
| 生命周期访问器（get_client / get_providers / resolve_api_key） | `app/llm/accessors.py` |

## H —— 驱动（`app/harness`）

### 内核模型与判定

| 职责 | 路径 |
|------|------|
| Run/Phase/Budget/Progress/Termination 状态模型 + P0-2 接缝（PhaseExecutionRequest/Outcome） | `app/harness/models.py` |
| 结构化决策模型与归一（三个保留控制工具 + parse_decision 五规则） | `app/harness/decision.py` |
| Action/Observation 指纹 + §12.4 六条件无进展判定 | `app/harness/progress.py` |
| PolicyDecision 模型（7 种结构化枚举） | `app/harness/policy/models.py` |
| 预算 / 动作 / 观察 / 组合 Policy | `app/harness/policy/{budget,action,observation,composite}.py` |
| 行动授权（身份 + 副作用审批矩阵，P0 边界） | `app/harness/policy/authorization.py` |
| Contract 定义/结果模型 + ContractExecutor（含 ScriptGate 抽象） | `app/harness/contracts/{models,executor}.py` |
| Contract 注册表 + 有界修复（decide_repair） | `app/harness/contracts/registry.py` |
| 结构契约校验（JSON Schema 子集：required + properties.type，阶段转换点与 Verifier 共用） | `app/harness/contracts/structural.py` |

### 执行与编排

| 职责 | 路径 |
|------|------|
| 阶段内 Bounded ReAct 执行器（ReactGraphState / BoundedReActExecutor + 端口 Protocol） | `app/harness/react/executor.py` |
| Bounded ReAct LangGraph 子图拓扑（§10 节点 + 条件边） | `app/harness/graph.py` |
| Tool Runtime 管线（preflight / 副作用预记录早于执行 / 幂等键 / broker / normalize / 产物） | `app/harness/execution/pipeline.py` |
| Workflow 定义模型（WorkflowDefinition / PhaseDefinition / PhaseExecutorType） | `app/harness/workflow/definition.py` |
| 阶段执行器注册表（ReactPhaseExecutor + RenderPhaseExecutor） | `app/harness/workflow/executors.py` |
| Workflow 编排（WorkflowRunner 顺序阶段推进 + input_bindings 绑定 + 阶段转换结构闸门/decide_repair 有界修复） | `app/harness/workflow/compiler.py` |
| 助手解析（用户显式选择，非 LLM 路由） | `app/harness/resolver/assistant.py` |
| 技能解析（SkillResolver 确定性策略链：显式→默认→唯一→首个） | `app/harness/resolver/skill.py` |
| Agent 执行入口（AgentAssembler 依赖 CapabilityActivatorPort / build_agent_budget / run_agent_turn / run_skill_workflow） | `app/harness/agent_runner.py` |

### 生命周期、事件与适配

| 职责 | 路径 |
|------|------|
| Run Service（create/resume/cancel/query/wait_for_input/pending_actions + RunQueryResult） | `app/harness/service.py` |
| 模型候选结果验证器（候选 ≠ 完成：PASS / NEEDS_INPUT / PARTIAL / FAIL） | `app/harness/verification.py` |
| 进行中回合句柄注册表（ActiveTurn / ActiveTurnRegistry：stop 取消、同会话并发 409） | `app/harness/turn.py` |
| Run 生命周期事件集（RunEvent 18 类 + 终态契约 + is_terminal） | `app/harness/events/run_events.py` |
| QueueEmitter（seq / 打字机 / 心跳 / 有界队列背压） | `app/harness/events/emitter.py` |
| Checkpoint 协议（SnapshotStore / EventLog / RunLease） | `app/harness/checkpoint/protocol.py` |
| 内存 Checkpoint store（测试与无 DB 默认） | `app/harness/checkpoint/memory.py` |
| Run 持久化实现（PostgreSQL 快照/事件/副作用 action 检查点 + Redis 租约/取消/心跳） | `app/application/run/persistence.py` |
| Run 持久化 ORM 载体（run_snapshots / run_events） | `app/infrastructure/database/models.py` |
| 生产适配器（LLMRunner / ActionGateway：抽象端口 → 真实运行组件） | `app/harness/wiring.py` |
| 能力装配端口（ToolBrokerPort / CapabilityActivatorPort，harness 不识别 MCP/Script 具体实现） | `app/harness/contracts/capability.py` |
| 助手目标词汇（AssistantTarget / TargetType / SelectionSource，保留字 generic） | `app/harness/targets.py` |

### 技能包（`app/harness/skill`）

| 职责 | 路径 |
|------|------|
| AGENT / SKILL 清单模型（AgentManifest + SkillManifest + 声明类 + SkillWorkflowDefinition） | `app/harness/skill/manifest.py` |
| Skill Pack 定义聚合（AgentPackage / AgentRegistrySnapshot / 加载失败项） | `app/harness/skill/definition.py` |
| 包扫描 + frontmatter 解析 + 加载期校验（绝对路径禁令） | `app/harness/skill/loader.py` |
| 两级索引（智能体/技能） | `app/harness/skill/index.py` |
| 技能装配（上下文注入 + 门禁注册 + workflow 透传，AssemblyPlan/SkillAssembler；**并投影出环境侧 `ToolActivationPlan`**） | `app/harness/skill/assemble.py` |
| 技能包运行时对齐契约（AGENT/SKILL 正文边界校验，告警不阻断） | `app/harness/skill/contract.py` |
| 注册表门面（AgentRegistry：扫描、两级索引、技能装配、热重载） | `app/harness/skill/registry.py` |
| 热重载（开关驱动、快照语义、后台轮询） | `app/harness/skill/hot_reload.py` |

## E —— 环境（`app/environment`）

### 工具与 MCP

| 职责 | 路径 |
|------|------|
| 工具端口词汇（ToolDescriptor / ToolCallRequest / ToolResult / 限定名规则） | `app/environment/tools/models.py` |
| **工具激活计划（环境侧端口形状：ScriptSpec / CapabilitySpec / ToolActivationPlan）** | `app/environment/tools/plan.py` |
| ToolBroker：激活、三级暴露、并发分发、截断 | `app/environment/tools/broker.py` |
| 脚本执行器（本地 subprocess、stdin/stdout、产物扫描） | `app/environment/tools/script_executor.py` |
| MCP 客户端（Streamable HTTP JSON-RPC） | `app/environment/mcp/client.py` |
| MCP 连接/引用计数管理器（acquire/release/close_idle） | `app/environment/mcp/manager.py` |
| MCP 生命周期访问器（get_manager / get_registry） | `app/environment/mcp/accessors.py` |

### 上下文平面（P1#9 拆分：事实/来源在 environment，取舍/投影在 harness）

| 职责 | 路径 |
|------|------|
| 上下文结构模型（AgentContext / ContextIdentity / ContextMessage / ContextDelta 等） | `app/environment/context/models.py` |
| 上下文来源端口（ConversationContextPort / AttachmentContextPort） | `app/environment/context/ports.py` |
| ContextAssembler（唯一装配入口：历史 + 附件 + 确定性裁剪 + 带版本上下文） | `app/harness/context/assembler.py` |
| ContextProjector（AgentContext → list[ChatMessage]） | `app/harness/context/projector.py` |

### 工作区 / 存储

| 职责 | 路径 |
|------|------|
| 智能体工作区（创建 / 路径校验 / 防穿越，按 account/conversation/run 隔离） | `app/environment/workspace/service.py` |
| 存储端口 + 类型枚举（BaseStorage / StorageType） | `app/environment/storage/{base,types}.py` |
| LocalStorage（UUID 扁平、anyio 线程池）/ S3 占位 | `app/environment/storage/{local,s3}.py` |
| 存储访问器（get_storage，按 storage_type 选择后端） | `app/environment/storage/accessors.py` |

## DDD 侧（业务承载）

### 对外接入（interfaces）

| 职责 | 路径 |
|------|------|
| 对话接口（POST /chat-messages + stop + 断线续传 replay/resume；参数提取、帧编码、响应构造） | `app/interfaces/http/chat.py` |
| 助手目录接口（GET /assistants，只读） | `app/interfaces/http/assistants.py` |
| 会话接口（/conversations 列表 / 消息 / 软删除） | `app/interfaces/http/conversations.py` |
| 文件接口（/files 上传 / 预览） | `app/interfaces/http/files.py` |
| 认证接口（登录 / elecnest / 刷新 / 登出 / 改密码 + /users/me） | `app/interfaces/http/auth.py` |
| FastAPI 认证依赖（get_current_account / require_superuser） | `app/interfaces/http/deps.py` |
| 应用容器依赖（get_services：从 app.state 取 AppServices） | `app/interfaces/http/deps.py` |
| 路由登录声明层（@login_required / @bearer_required / @public + LoginRoute） | `app/interfaces/http/auth_guard.py` |
| RunEvent → SSE 帧映射（终态契约 / is_terminal 再导出） | `app/interfaces/sse/frames.py` |
| 对话 SSE / 请求响应模型（chat-messages 对外契约） | `app/interfaces/schemas/chat.py` |
| 接入层 DTO 门面（转发 application 层 DTO） | `app/interfaces/schemas/__init__.py` |
| 全局异常中间件 / 请求日志中间件 | `app/interfaces/middleware/{exceptions,request_logging}.py` |

### 应用层（application）

| 职责 | 路径 |
|------|------|
| 应用服务容器（AppServices：单例集合 + assistant_catalog 访问） | `app/application/services.py` |
| 回合执行（Run 生命周期：专家 ReAct / 技能 Workflow / 通用直连流式） | `app/application/chat/run_turn.py` |
| 回合生命周期（并发登记 409 / 终态释放锁 / 全路径兜底落库） | `app/application/chat/turn_lifecycle.py` |
| 回合上下文装配（AppServices + 会话身份 → AgentContext → LLM 消息投影） | `app/application/chat/turn_context.py` |
| 上下文来源端口适配器（ConversationService → 结构化会话消息；业务侧适配到环境端口） | `app/application/context/adapters.py` |
| 能力装配适配器（CapabilityActivator：工作区创建 + ToolBroker 激活，实现 CapabilityActivatorPort） | `app/application/agent/capability.py` |
| 对话历史落库/读取/删除 + 用量聚合（ConversationService，DB 降级内部消化） | `app/application/conversation/service.py` |
| TurnRecorder（RunEvent 流 → TurnRecord 落库载荷） | `app/application/conversation/recorder.py` |
| 文件注册表服务（register / upload / 预览 / 使用标记） | `app/application/file/service.py` |
| 账号认证门面（AuthService：平台验签 / 本地账号解析 / 资料维护 / 用量） | `app/application/identity/service.py` |
| 本地账号管理 CLI（python -m app.application.identity.provision） | `app/application/identity/provision.py` |
| AssistantCatalog（专家目录：读技能注册表投影为可选助手清单） | `app/application/assistant/catalog.py` |
| 会话历史 DTO（ConversationRecord / ConversationSession / TurnRecord / UsageAggregate） | `app/application/dto/conversations.py` |
| 文件 DTO（ArtifactRecord / FileResponse / UploadConfig） | `app/application/dto/files.py` |
| 认证 DTO（AccountRecord / 登录·刷新·登出·改密码请求体 / UserUsage / AvatarConfig） | `app/application/dto/auth.py` |

### 领域层（domain，零框架零 I/O）

| 职责 | 路径 |
|------|------|
| 会话域词汇（DTO 在 application/dto，用例在 application/conversation） | `app/domain/conversation/__init__.py` |
| 文件域词汇（用例在 application/file，存储在 environment/storage） | `app/domain/file/__init__.py` |
| 账号枚举 / 平台令牌载荷 / SSO 用户资料投影 | `app/domain/identity/models.py` |
| 会话存储端口（KeyValueStore / SessionStore 协议，fail-closed 契约） | `app/domain/identity/ports.py` |

### 基础设施（infrastructure，共享技术底座）

| 职责 | 路径 |
|------|------|
| SQLAlchemy 声明式基类 + 命名约定 + 本地时间 | `app/infrastructure/database/base.py` |
| 异步引擎 + 会话工厂（连接池配置驱动） | `app/infrastructure/database/engine.py` |
| ORM 模型（accounts / conversations / messages / upload_files / agent_packages / agent_package_entries / run_snapshots / run_events / run_action_records） | `app/infrastructure/database/models.py` |
| 数据库访问器（get_database） | `app/infrastructure/database/accessors.py` |
| Redis 客户端 + Cache/Lock 封装 + 访问器 | `app/infrastructure/redis/client.py` |
| 登录会话存储实现（RedisSessionStore，fail-closed 异常边界） | `app/infrastructure/redis/session_store.py` |
| 密码哈希（Argon2id）与 JWT 签发/验签（HS256） | `app/infrastructure/crypto/security.py` |
| 公司统一登录客户端（elecnest SSO，httpx） | `app/infrastructure/sso/elecnest.py` |
| 日志内核（脱敏 / trace 上下文）+ 生命周期访问器 | `app/infrastructure/logging/{logging,accessors}.py` |

## 跨层共享（config / shared）

| 职责 | 路径 |
|------|------|
| 全局配置（pydantic-settings + active_settings/set_active_settings） | `app/config/settings.py` |
| 注册表/配置 YAML 加载（LLM 提供方 / MCP 服务） | `app/config/loader.py` |
| 领域异常 + 错误分类（ErrorCategory / PlatformError / 各域异常） | `app/shared/errors/base.py` |
| 事件/错误消息脱敏与截断 | `app/shared/utils/sanitize.py` |
| 中文 grapheme 切分 | `app/shared/utils/graphemes.py` |

## 数据与配置（非代码）

| 内容 | 路径 |
|------|------|
| discover 智能体包（三级结构 `agents/{agent}/{skill}`） | `agents/discover/` |
| discover-new 智能体包 | `agents/discover-new/` |
| credit-period 智能体包 | `agents/credit-period/` |
| 本地自建 MCP 服务聚合包（tencent_mcp + eastmoney_mcp） | `local_mcp/` |
| MCP 服务注册表 / LLM 提供方注册表 | `config/mcp-servers.yaml`、`config/llm-providers.yaml`（example 可提交） |
| 管理端技能包标准模板（AGENT/SKILL/references/templates） | `agent_package_templates/standard/` |
| 环境变量模板 | `.env.example` |
| 单元测试（无网络 / 无 DB；含边界守卫 `test_layering.py`） | `tests/unit/` |
| 集成测试（依赖本地 PostgreSQL） | `tests/integration/` |
| HTTP 接入层测试（TestClient 进程内 ASGI） | `tests/http/` |
| 端到端测试（需真服务，未启动自动 skip） | `tests/e2e/` |
