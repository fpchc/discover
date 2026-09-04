# 模块地图（职责 → 文件路径）

> 新增/删除模块文件后必须同步更新本表。2026-09-02 目录重构快照（按业务核心分层 +
> 基础设施下沉，替代原 L0–L5 技术横切分层，见 ARCHITECTURE.md「目录重构」行）。
> 二轮（2026-09-02 下午）：domain/agent → domain/skill + manifest/definition 拆分、
> 解析器归 runtime/resolver、新增 runtime/execution、extensions 摊平单文件 + 访问器归位、
> 新增 infrastructure/redis、storage/logging 文件改名。

## 组合根（bootstrap）

| 职责 | 路径 |
|------|------|
| 应用组装工厂（create_app：扩展 + 中间件 + 路由挂载） | `app/bootstrap/application.py` |
| 服务容器 DI（扩展访问器 + 领域组装 + assistant_catalog + get_runtime） | `app/bootstrap/container.py` |
| 进程入口（uvicorn 启动，host/port 配置驱动） | `app/main.py` |
| 扩展加载器（EXTENSIONS 有序元组 + initialize/startup/shutdown；只组装不实现） | `app/bootstrap/extensions.py` |
| 当前应用配置访问（active_settings / set_active_settings，随配置层归位） | `app/config/settings.py` |

## 对外接入（interfaces）

| 职责 | 路径 |
|------|------|
| 对话接口（POST /chat-messages SSE/blocking + stop，agent_id 显式绑定；expert 走 Agent 技能包 ReAct 路径，通用走直接流式） | `app/interfaces/http/chat.py` |
| 助手目录接口（GET /assistants，只读聚合） | `app/interfaces/http/assistants.py` |
| 会话接口（/conversations 列表/消息/软删除；按账号隔离） | `app/interfaces/http/conversations.py` |
| 文件接口（/files 上传/预览，预览全局公开） | `app/interfaces/http/files.py` |
| 认证接口（/auth/login、/users/me 等） | `app/interfaces/http/auth.py` |
| FastAPI 认证依赖（get_current_account_id / require_superuser） | `app/interfaces/http/deps.py` |
| 会话历史 DTO（ConversationRecord/TurnRecord/UsageAggregate/ConversationSession） | `app/interfaces/schemas/conversations.py` |
| 文件 DTO（ArtifactRecord/FileResponse/UploadConfig） | `app/interfaces/schemas/files.py` |
| 认证 DTO（LoginRequest/ElecnestUserInfo/AccountRecord/UserUsage/AvatarConfig） | `app/interfaces/schemas/auth.py` |
| 对话 SSE / 请求响应模型（chat-messages 契约） | `app/interfaces/schemas/chat.py` |
| 全局异常中间件（领域异常 → 统一 JSON） | `app/interfaces/middleware/exceptions.py` |
| 请求日志中间件（request_id / trace_id / 耗时） | `app/interfaces/middleware/request_logging.py` |

## 业务域（domain）

### skill 注册域（Skill Pack：manifest 模型 / definition 聚合 / loader 加载）

| 职责 | 路径 |
|------|------|
| frontmatter 模型（AgentManifest + SkillManifest + 声明类） | `app/domain/skill/manifest.py` |
| Skill Pack 定义聚合（AgentPackage / AgentRegistrySnapshot / 加载失败项） | `app/domain/skill/definition.py` |
| 包扫描 + frontmatter 解析 + 加载期校验（绝对路径禁令） | `app/domain/skill/loader.py` |
| 两级索引（智能体/技能） | `app/domain/skill/index.py` |
| 技能装配（上下文注入 + 门禁脚本注册，AssemblyPlan/SkillAssembler） | `app/domain/skill/assemble.py` |
| 热重载（开关驱动、快照语义） | `app/domain/skill/hot_reload.py` |
| 注册表门面（AgentRegistry） | `app/domain/skill/registry.py` |

### assistant 选择域

| 职责 | 路径 |
|------|------|
| AssistantTarget / TargetType / SelectionSource（保留字 generic） | `app/domain/assistant/models.py` |
| AssistantCatalog（专家目录，capabilities 取技能；经 app.domain 门面访问） | `app/domain/assistant/catalog.py` |

### 会话 / 工作区 / 文件 / 认证

| 职责 | 路径 |
|------|------|
| 对话历史落库/读取/删除 + 用量聚合（ConversationService，DB 降级内部消化） | `app/domain/conversation/service.py` |
| 智能体工作区（创建/路径校验/防穿越，按 agent 键控） | `app/domain/workspace/service.py` |
| 文件注册表服务（register/upload/upload_avatar/预览/使用标记） | `app/domain/file/service.py` |
| 账号认证门面（AuthService：login/validate_session/refresh/logout/资料维护） | `app/domain/auth/service.py` |
| 登录会话存储（SessionStore 协议 + RedisSessionStore fail-closed） | `app/domain/auth/session.py` |
| 公司统一登录客户端（elecnest SSO） | `app/domain/auth/sso.py` |
| Argon2id 密码哈希 + JWT 访问令牌（PasswordHasher / JwtService） | `app/domain/auth/security.py` |
| 预置账号 CLI（python -m app.domain.auth.provision，无注册接口） | `app/domain/auth/provision.py` |

## Agent 执行内核（runtime）

### Agent Runtime（react-runtime-v2-architecture；正式内核，旧 V1 Runtime 已全量下线）

| 职责 | 路径 |
|------|------|
| Run/Phase/Budget/Progress/Termination 状态模型 + P0-2 接缝（PhaseExecutionRequest/Outcome/PhaseOutput） | `app/runtime/models.py` |
| Agent 解析/技能装配/单阶段 ReAct 执行入口（AgentAssembler/run_agent_turn/build_agent_budget） | `app/runtime/agent_runner.py` |
| 结构化决策模型与归一（三个保留控制工具 + parse_decision 五规则，P0-1） | `app/runtime/react/decision.py` |
| Bounded ReAct 执行器节点逻辑（ReactGraphState/BoundedReActExecutor + Protocol 端口） | `app/runtime/react/executor.py` |
| Action/Observation 指纹 + §12.4 六条件无进展判定 | `app/runtime/react/progress.py` |
| PolicyDecision 模型（7 种结构化枚举） | `app/runtime/policy/models.py` |
| 预算 Policy（软/硬边界判定） | `app/runtime/policy/budget.py` |
| Action Policy（存在性/白名单/schema/重复无进展） | `app/runtime/policy/action.py` |
| Observation Policy（空返回/重复/错误/降级） | `app/runtime/policy/observation.py` |
| 组合 Policy（按严重度取最高） | `app/runtime/policy/composite.py` |
| Contract 定义/结果模型（三类 + PASS/WARN/FAIL） | `app/runtime/contracts/models.py` |
| ContractExecutor（structural/quality/evidence + ScriptGate 统一 Gate） | `app/runtime/contracts/executor.py` |
| Contract 注册表 + 有界修复（decide_repair） | `app/runtime/contracts/registry.py` |
| Bounded ReAct LangGraph 子图拓扑（§10 节点 + 条件边） | `app/runtime/graph.py` |
| Tool Runtime 管线（preflight/副作用/幂等键/broker/normalize/产物） | `app/runtime/execution/pipeline.py` |
| Run 生命周期事件集（RunEvent 18 类 + 终态契约） | `app/runtime/events/run_events.py` |
| QueueEmitter（seq/打字机/心跳/有界队列背压） | `app/runtime/events/emitter.py` |
| Checkpoint 协议（SnapshotStore/EventLog/RunLease） | `app/runtime/checkpoint/protocol.py` |
| 内存 Checkpoint store（测试与无 DB 默认） | `app/runtime/checkpoint/memory.py` |
| Run Service（create/resume/cancel/query + RunQueryResult） | `app/runtime/service.py` |
| Workflow 定义模型（WorkflowDefinition/PhaseDefinition/PhaseExecutorType） | `app/runtime/workflow/definition.py` |
| 阶段执行器注册表（ReactPhaseExecutor + PhaseExecutorRegistry） | `app/runtime/workflow/executors.py` |
| Workflow 编排（WorkflowRunner 顺序阶段推进 + input_bindings 绑定） | `app/runtime/workflow/compiler.py` |
| 生产适配器（LLMRunner/ToolRunner/SSEEventSink：抽象端口 → 真实运行组件） | `app/runtime/wiring.py` |
| 进行中回合句柄注册表（ActiveTurn/ActiveTurnRegistry：stop 取消；同会话并发 409） | `app/runtime/turn.py` |
| 助手解析（用户显式选择，非 LLM 路由） | `app/runtime/resolver/assistant.py` |
| 技能解析（SkillResolver 确定性策略链：显式→默认→唯一→首个） | `app/runtime/resolver/skill.py` |
| 对话回合执行（v2 Run 生命周期：Run 创建 / 专家与通用执行路径 / 终态事件） | `app/interfaces/http/chat_execution.py` |
| Run 事件 → SSE 帧映射（终态契约/is_terminal） | `app/interfaces/http/run_stream.py` |

### 回合事件聚合（领域层）

| 职责 | 路径 |
|------|------|
| TurnRecorder（RunEvent 流 → TurnRecord 落库载荷；终态状态映射 + exit_reason 兜底） | `app/domain/conversation/recorder.py` |

## 能力层（capabilities）

| 职责 | 路径 |
|------|------|
| LLM 客户端（httpx + 流式） | `app/capabilities/llm/client.py` |
| LLM 请求/响应/工具模型 | `app/capabilities/llm/models.py` |
| 提供方注册表 + 别名解析 + 密钥解析 | `app/capabilities/llm/providers.py` |
| 流式分块解析（Text/Thinking/ToolCalls/Finish） | `app/capabilities/llm/stream_parser.py` |
| 回合用量聚合（UsageAggregator） | `app/capabilities/llm/usage.py` |
| LLM 特定异常 | `app/capabilities/llm/errors.py` |
| LLM 生命周期访问器（get_client / get_providers / resolve_api_key） | `app/capabilities/llm/accessors.py` |
| ToolBroker：激活、三级暴露、并发分发 | `app/capabilities/tools/broker.py` |
| 工具描述/限定名/chat spec | `app/capabilities/tools/descriptor.py` |
| 脚本执行器（本地 subprocess、stdin/stdout、产物扫描） | `app/capabilities/tools/script_executor.py` |
| 去重历史（DedupStore，dedup_clues 按账号隔离，脚本纯计算契约） | `app/capabilities/tools/history.py` |
| MCP 客户端（Streamable HTTP JSON-RPC） | `app/capabilities/mcp/client.py` |
| MCP 连接/引用计数管理器（acquire/release/close_idle） | `app/capabilities/mcp/manager.py` |
| MCP 生命周期访问器（get_manager / get_registry） | `app/capabilities/mcp/accessors.py` |

## 基础设施（infrastructure）

| 职责 | 路径 |
|------|------|
| SQLAlchemy 声明式基类 + 命名约定 + UTC 时间 | `app/infrastructure/database/base.py` |
| 异步引擎 + 会话工厂（NullPool 即开即关） | `app/infrastructure/database/engine.py` |
| ORM 模型（accounts/conversations/messages/upload_files/dedup_clues） | `app/infrastructure/database/models.py` |
| 数据库生命周期访问器（get_database） | `app/infrastructure/database/accessors.py` |
| Redis 客户端 + Cache/Lock 封装 + 访问器（认证会话层硬依赖） | `app/infrastructure/redis/client.py` |
| BaseStorage 抽象（save/load_once/load_stream/download/exists/delete/url/scan） | `app/infrastructure/storage/base.py` |
| StorageType 枚举（local / s3 预留） | `app/infrastructure/storage/types.py` |
| LocalStorage（UUID 扁平、anyio 线程池） | `app/infrastructure/storage/local.py` |
| S3 后端占位（扩展点，未实现） | `app/infrastructure/storage/s3.py` |
| 存储生命周期访问器（get_storage，按 storage_type 选择后端） | `app/infrastructure/storage/accessors.py` |
| 日志内核（SensitiveDataFilter / TraceFilter / trace 上下文 / 模块级别） | `app/infrastructure/logging/logging.py` |
| 日志生命周期访问器（非阻塞 QueueHandler/QueueListener 结构化日志） | `app/infrastructure/logging/accessors.py` |

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
| discover 智能体包（三级结构：`agents/{agent}/{skill}`） | `agents/discover/` |
| discover-new 智能体包（候选池评分推荐） | `agents/discover-new/` |
| credit-assessment 智能体包 | `agents/credit-assessment/` |
| credit-period 智能体包（账期评估 F/R/S 三因子） | `agents/credit-period/` |
| 本地自建 MCP 服务聚合包（tencent_mcp + eastmoney_mcp，Facade） | `local_mcp/` |
| 迁移源（只读历史参考） | `eitia-client-finder/` |
| MCP 服务注册表 | `config/mcp-servers.yaml`（example 可提交） |
| LLM 提供方注册表 | `config/llm-providers.yaml`（example 可提交） |
| 环境变量模板 | `.env.example` |
| 单元测试（无网络 / 无 DB） | `tests/unit/` |
| 集成测试（依赖本地 PostgreSQL） | `tests/integration/` |
| HTTP 接入层测试（TestClient 进程内 ASGI） | `tests/http/` |
| 端到端测试（需真服务 127.0.0.1:8000，未启动自动 skip） | `tests/e2e/` |
| 测试共享 fixture（make_test_app / make_client + 四层 marker 自动打标） | `tests/conftest.py` |
