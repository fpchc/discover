# 模块地图（职责 → 文件路径）

> 新增/删除模块文件后必须同步更新本表。P1 快照：2026-08。

## 基础层（L0）

| 职责 | 路径 |
|------|------|
| 全局配置（pydantic-settings） | `app/config/settings.py` |
| 注册表/配置 YAML 加载 | `app/config/loader.py` |
| 领域异常 + 错误分类（含 ConflictError → 409） | `app/errors/base.py` |
| AgentEvent 事件模型 | `app/protocol/events.py` |
| QueueEmitter（seq/打字机/心跳/背压） | `app/protocol/emitter.py` |
| 事件/错误消息脱敏 | `app/protocol/sanitize.py` |
| 中文 grapheme 切分 | `app/protocol/graphemes.py` |

## 持久化层（L0，db）

| 职责 | 路径 |
|------|------|
| SQLAlchemy 声明式基类 + 命名约定 + UTC 时间 | `app/db/base.py` |
| 异步引擎 + 会话工厂（NullPool 即开即关） | `app/db/engine.py` |
| ORM 模型（accounts / conversations / messages / upload_files / dedup_clues；既有表带 from_account_id / created_by 账号关联） | `app/db/models.py` |

## 存储层（L0，extensions/storage，Blob Engine）

| 职责 | 路径 |
|------|------|
| BaseStorage 抽象（save/load_once/load_stream/download/exists/delete/url/scan） | `app/extensions/storage/base_storage.py` |
| StorageType 枚举（local / s3 预留） | `app/extensions/storage/storage_type.py` |
| LocalStorage（UUID 扁平、anyio 线程池） | `app/extensions/storage/local_storage.py` |
| S3 后端占位（扩展点，未实现） | `app/extensions/storage/aws_s3_storage.py` |

## 业务服务层（L0/L1，services）

| 职责 | 路径 |
|------|------|
| 对话历史落库/读取/删除（ConversationService，按账号隔离；DB 降级内部消化，舱壁）+ 账号 token 用量聚合（aggregate_user_usage / usage_by_account） | `app/services/conversations.py` |
| 文件注册表服务（register/upload/upload_avatar 头像校验/预览/使用标记，FileService + file_preview_path） | `app/services/files.py` |
| 智能体工作区（创建/路径校验/防穿越，按 agent 键控跨会话共享，WorkspaceManager / Workspace） | `app/services/workspace.py` |

## 持久化仓库层（L0，repositories）

| 职责 | 路径 |
|------|------|
| 去重历史注入/回写（dedup_clues 表按账号隔离 + 组合主键 (created_by, clue_id)，脚本纯计算契约，DedupStore） | `app/repositories/dedup.py` |

## 账号认证（L0/L4，services/auth + api/deps）

| 职责 | 路径 |
|------|------|
| 账号认证门面（login / login_with_elecnest / validate_session / refresh / logout / get_account / get_user_usage / list_users_with_usage + 资料维护：update_account / change_avatar / change_password / avatar_config，AuthService） | `app/services/auth.py` |
| 登录会话存储层（访问/刷新令牌 Redis 会话：SessionStore 协议 + RedisSessionStore fail-closed + NullSessionStore 降级 + key 规范 `auth:access\|refresh:{sha256}`） | `app/services/auth_session.py` |
| 公司统一登录客户端（elecnest SSO：token + uid → 用户资料，ElecnestSSOClient） | `app/services/elecnest_sso.py` |
| Argon2id 密码哈希 + JWT 访问令牌（PasswordHasher / JwtService，exp 取 `auth_access_token_ttl_seconds`） | `app/services/auth_security.py` |
| FastAPI 认证依赖（get_current_account_id async 会话校验 / get_bearer_token / get_current_account / require_superuser） | `app/api/deps.py` |
| 认证接口（/auth/login、/auth/login/elecnest、/auth/refresh、/auth/logout、/users/me、/users/me/usage、/users/me/avatar-config、PATCH /users/me、/users/me/avatar、/users/me/password、/users 超级用户） | `app/api/auth.py` |
| 预置账号 CLI（python -m app.services.auth_provision，无注册接口） | `app/services/auth_provision.py` |

## LLM 层（L1）

| 职责 | 路径 |
|------|------|
| LLM 客户端（httpx + 流式） | `app/llm/client.py` |
| 请求/响应/工具模型 | `app/llm/models.py` |
| 提供方注册表 + 别名解析 + 密钥解析 | `app/llm/providers.py` |
| 流式分块解析（Text/Thinking/ToolCalls/Finish） | `app/llm/stream_parser.py` |
| LLM 特定异常 | `app/llm/errors.py` |

## 数据契约层（L0，schemas）

| 职责 | 路径 |
|------|------|
| 会话历史 DTO（ConversationRecord / MessageRecord / TurnRecord 含 account_id / UsageAggregate / ConversationSession） | `app/schemas/conversations.py` |
| 文件 DTO（ArtifactRecord 产物事件 / FileResponse / UploadConfig） | `app/schemas/files.py` |
| 认证 DTO（LoginRequest / ElecnestLoginRequest / ElecnestUserInfo / LoginResponse / AccountRecord / UserUsage / AccountStatus / UserType + 资料维护：UpdateAccountRequest / ChangePasswordRequest / AvatarConfig） | `app/schemas/auth.py` |
| 对话 SSE / 请求响应模型（chat-messages 契约） | `app/schemas/chat.py` |

## 工具层（L1/L2）

| 职责 | 路径 |
|------|------|
| ToolBroker：激活、三级暴露、并发 | `app/tools/broker.py` |
| 工具描述/限定名/chat spec | `app/tools/descriptor.py` |
| MCP 客户端（Streamable HTTP JSON-RPC） | `app/tools/mcp_client.py` |
| MCP 进程/连接池（引用计数、空闲回收） | `app/tools/mcp_manager.py` |
| 脚本执行器（本地 subprocess、stdin/stdout、产物扫描） | `app/tools/script_executor.py` |

## 装配层（L2，registry）

| 职责 | 路径 |
|------|------|
| AGENT/SKILL 清单模型 | `app/registry/manifests.py` |
| 包扫描 + frontmatter 解析 + 加载期校验（绝对路径禁令） | `app/registry/loader.py` |
| 两级索引（智能体/技能） | `app/registry/index.py` |
| 技能装配（上下文注入 + 门禁脚本注册） | `app/registry/assemble.py` |
| 热重载（开关驱动、快照语义） | `app/registry/hot_reload.py` |
| 注册表门面 | `app/registry/registry.py` |

## 助手目录层（L2，catalog）

| 职责 | 路径 |
|------|------|
| AssistantTarget / TargetType / SelectionSource（选择域模型，保留字 generic） | `app/catalog/models.py` |
| AssistantCatalog（专家目录，capabilities 取技能；通用对话为未绑定默认） | `app/catalog/assistant_catalog.py` |

## 图运行时层（L3，runtime）

| 职责 | 路径 |
|------|------|
| GraphState / GateStatus（active_target: AssistantTarget） | `app/runtime/state.py` |
| 助手解析（读会话显式绑定，非 LLM 路由；未来 Policy/Workflow 插入） | `app/runtime/resolver/assistant_resolver.py` |
| 技能解析（SkillResolver 确定性策略链：显式→默认→唯一→首个） | `app/runtime/resolver/skill_resolver.py` |
| 节点实现（resolve_assistant / resolve_skill / assemble / agent / tool_node / generic_chat）+ 单轮执行入口 + 上下文裁剪 | `app/runtime/runner.py` |
| LangGraph 拓扑构建 | `app/runtime/builder.py` |
| 进行中回合句柄注册表（ActiveTurn/ActiveTurnRegistry：stop 接口取消；同会话并发 409 门；task.cancel == 客户端断连原语） | `app/runtime/active_turns.py` |

## 接入层（L4）

| 职责 | 路径 |
|------|------|
| 应用组装（工厂 + 扩展初始化 + 中间件注册 + 路由挂载） | `app/application.py` |
| 进程入口（uvicorn 启动，host/port 配置驱动） | `app/main.py` |
| 服务容器 DI：扩展访问器 + 领域组装 + assistant_catalog() | `app/container.py` |
| 对话接口（POST /chat-messages SSE/blocking + POST /chat-messages/{id}/stop，agent_id 显式绑定；Bearer 认证，会话归属账号；同会话并发 409） | `app/api/chat.py` |
| 助手目录接口（GET /assistants，只读聚合，公开） | `app/api/assistants.py` |
| 文件接口（上传需认证带归属账号；预览全局公开） | `app/api/files.py` |
| 会话接口（/conversations 列表/消息/软删除；按账号隔离，跨账号 404） | `app/api/conversations.py` |
| 认证接口（/auth/login 公开；/users/me、/users/me/usage、/users/me/avatar-config、PATCH /users/me、/users/me/avatar、/users/me/password、/users 超级用户） | `app/api/auth.py` |

## 扩展层（L1，extensions，基础设施统一加载）

| 职责 | 路径 |
|------|------|
| 扩展加载器（EXTENSIONS 有序元组 + initialize/startup/shutdown） | `app/extensions/__init__.py` |
| 配置访问间接层（active_settings / set_active_settings） | `app/extensions/base.py` |
| logging 扩展（非阻塞 QueueHandler/QueueListener 结构化日志） | `app/extensions/ext_logging.py` |
| db 扩展（SQLAlchemy 异步引擎 + 会话工厂） | `app/extensions/ext_database.py` |
| redis 扩展（客户端 + Cache/Lock 封装，默认关闭） | `app/extensions/ext_redis.py` |
| storage 扩展（BaseStorage 后端选择，local / s3 预留） | `app/extensions/ext_storage.py` |
| mcp 扩展（MCP 注册表 + MCPManager 引用计数） | `app/extensions/ext_mcp.py` |
| llm 扩展（LLMClient + ProviderRegistry + 密钥解析） | `app/extensions/ext_llm.py` |

## 内核层（L0/L1，kernel）

| 职责 | 路径 |
|------|------|
| 日志内核（SensitiveDataFilter / TraceFilter / trace 上下文 / 模块级别） | `app/kernel/logging.py` |

## 中间件层（L4，middleware）

| 职责 | 路径 |
|------|------|
| 全局异常中间件（领域异常 → 统一 JSON，泛型兜底 500 + traceback） | `app/middleware/exceptions.py` |
| 请求日志中间件（request_id / X-Request-Id / trace_id / 耗时 / client_ip） | `app/middleware/request_logging.py` |
| 对话接口（/chat-messages，SSE / blocking，controller） | `app/api/chat.py` |
| 文件路由（/files/upload 配置、上传、{id}/preview 流式预览，controller） | `app/api/files.py` |
| 会话接口（/conversations 列表/消息/软删除，controller） | `app/api/conversations.py` |

## 数据与配置（非代码）

| 内容 | 路径 |
|------|------|
| discover 智能体包（三级结构：`agents/discover/client-finder/`） | `agents/discover/` |
| discover-new 智能体包（客户调研：候选池评分推荐最优一家，输出 300 字信息卡；三级结构：`agents/discover-new/client-finder/`） | `agents/discover-new/` |
| credit-period 智能体包（账期评估：单客户 F/R/S 三因子评分，输出完整账期评估文字报告；三级结构：`agents/credit-period/period-assessment/`） | `agents/credit-period/` |
| credit-period 脚本：评分计算 / 门禁校验（period_calculator / gate_report_valid，stdin JSON 契约） | `agents/credit-period/period-assessment/scripts/` |
| credit-period 脚本入参约束（period_input / gate_input，模型可见参数 schema） | `agents/credit-period/period-assessment/schemas/` |
| discover 脚本入参约束（score/render/dedup/gate，模型可见参数 schema） | `agents/discover/client-finder/schemas/` |
| discover 报告数据契约单一事实来源（required_fields/optional/compat，驱动 render_report.check_completeness） | `agents/discover/client-finder/schemas/report_schema.json` |
| discover 脚本：评分 / 去重 / 渲染 / 门禁校验（stdin JSON 契约） | `agents/discover/client-finder/scripts/` |
| 门禁声明入参约束（`GateDeclaration.schema_path` → 校验器脚本工具） | `app/registry/manifests.py` |
| 迁移源（只读历史参考） | `eitia-client-finder/` |
| MCP 服务注册表 | `config/mcp-servers.yaml`（example 可提交） |
| LLM 提供方注册表 | `config/llm-providers.yaml`（example 可提交） |
| 环境变量模板 | `.env.example` |
| 单元测试（无网络 / 无 DB） | `tests/unit/` |
| 集成测试（依赖本地 PostgreSQL） | `tests/integration/` |
| HTTP 接入层测试（TestClient 进程内 ASGI） | `tests/http/` |
| 端到端测试（需真服务 127.0.0.1:8000，未启动自动 skip） | `tests/e2e/` |
| 测试共享 fixture（make_test_app / make_client + 四层 marker 自动打标） | `tests/conftest.py` |
