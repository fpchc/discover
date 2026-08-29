# 多智能体承载平台架构快照

> P1 状态（2026-08）：12 步构建完成，discover 智能体已迁移接入。对话接口为
> 对话接口 `POST /chat-messages`（会话自动创建）；审批机制、`/models`、`/agents`、
> 会话删除接口已按用户决策移除。账号认证已接入（2026-08-28）：accounts 表
> （手机号+密码 Argon2id + JWT）、既有表按 from_account_id/created_by 隔离、
> 用量按账号聚合、无注册接口（CLI 预置）。脚本执行已去容器化（2026-08-21 用户决策）：
> 宿主 subprocess 本地直跑，Docker 不再是前置条件。持久化已入 PostgreSQL
> （SQLAlchemy async + Alembic）；对话历史落库（conversations 会话头 + messages
> 回合明细，usage 含缓存 token 聚合）；产物/文件走 Blob Engine（字节入存储层、
> 元数据入库，upload_files 为多消费方共享注册表）；去重历史入 `dedup_clues` 表
> （脚本纯计算）；技能包三级结构 `agents/{agent}/{skill}`（无 skills/ 壳与 shared/），
> 工作区 `workspaces/{agent}` 按 agent 键控、跨会话共享。全套测试 179 通过
> （2 跳过：本地 8000 真服务用例）。随代码演进持续同步；一次性任务报告不写入本文件。

## 分层与依赖方向

依赖只能自上而下，禁止反向 import。

```
L5  frontend/                  Chat UI（消费事件判别流）｜P1 未实现
L4  api/（controller）          FastAPI 路由；应用组装（application.py）、DI（container.py）、DTO（schemas/）随接入层；
                               中间件（middleware/：全局异常 + 请求日志）挂接入层；扩展（extensions/：基础设施统一加载）由容器消费
L3  runtime/                   LangGraph 图：route_agent → route_skill → assemble
                                → agent ⇄ tool_node，generic_chat 兜底
L2  registry/ + tools/broker   装配层：清单解析/索引/热重载/装配；ToolBroker 工具目录与三级暴露
L1  llm/ + tools/(mcp|script) + services/
                               LLM 客户端、MCP（Streamable HTTP）、宿主 subprocess 脚本执行器（本地直跑）、
                               业务服务层（会话历史/文件/工作区/认证）统一收拢
L0  db/ + extensions/storage + repositories/ + config/ + errors/ + protocol/ + kernel/
                               SQLAlchemy/ORM（PostgreSQL）、Blob 存储、持久化仓库（去重历史）、
                               配置载体、领域异常、事件发射器；跨边界 DTO 统一在 schemas/
```

L3 不直接认识 MCP 与脚本：只向 `ToolBroker` 要工具列表，向注册表要装配上下文。
图中无任何智能体名 / 技能名 / 工具名字面量——唯一耦合面是 `AGENT.md` / `SKILL.md` 清单。

## 关键设计决策

| 决策 | 结论 | 依据 |
|------|------|------|
| 包根名 | `app`（仓库根单层包，去除 src/ 包裹与 platform_engine 层；api/ 仅路由） | 用户决策 2026-08 |
| 业务流程载体 | 图只提供执行环境，流程知识写在智能体/技能清单正文 | graph-runtime-spec §1 |
| 助手选择 | 用户**显式选择**（`GET /assistants` 目录 + `chat-messages.agent_id`），非 LLM 路由；会话绑定 `assistant_target(type+id)`；图节点 `resolve_assistant`（读会话绑定）→ `resolve_skill`（SkillResolver 确定性策略链）；未绑定走通用对话 | 用户决策 2026-08，graph-runtime-spec §4 |
| 助手类型体系 | 目录聚合专家（`agents/` 包，`kind: agent` + `type: expert`，类 Claude Code）；通用对话（`generic` 保留字）为未绑定默认，**不列入目录**；简单技能属未来 `kind: skill`，**非 agent 类型** | 用户决策 2026-08 |
| 技能耦合面 | 唯一耦合面是 `AGENT.md` / `SKILL.md` frontmatter | agent-package-spec |
| 工具命名空间 | MCP = `server.tool`；脚本 = `agent.skill.script.name`；元工具无前缀 | tool-broker-spec |
| 工具暴露 | 三级：Tier0 元工具 / Tier1 核心 / Tier2 懒加载 | tool-broker-spec |
| 脚本执行 | **P1 宿主 subprocess 直跑**（`sys.executable`，cwd=工作区，不做容器隔离）；脚本内禁止绝对路径字面量；对外开放脚本编辑后再评估轻量沙箱 | 用户决策 2026-08，script-sandbox-spec |
| 脚本路径归一 | `agents_root_dir` 在 `AgentRegistry` 归一为绝对路径（`Path.resolve()`）——技能目录 / 脚本宿主路径 / `SKILL_ROOT_DIR` 一律绝对；否则 subprocess cwd=工作区会把相对脚本路径按工作区解析而找不到（实测：dedup_manager "No such file or directory"） | 实测修复 2026-08-24 |
| 脚本入参契约 | 平台一律经 stdin 传 JSON，脚本须从 stdin 读入参；声明 `schema_path` 让模型可见正确参数约束。缺省 schema 只有 `input` 字段，多字段脚本（dedup/render/gate）必须补 schema，否则参数与脚本实际读取字段错位（实测：报告管线全部 `执行失败`） | 实测修复 2026-08-23 |
| 报告数据闭环 | AI 无写文件工具，报告 JSON 只能经 stdin 到达脚本；`render_report` 入参 **`data` 内联必填**（schema 移除 `input` 路径选项），渲染时把数据落盘 `output/report.json`；`gate_render_pass` 经 `report_json` 引用该落盘文件（`GateDeclaration.schema_path` 挂载校验器入参约束） | 实测修复 2026-08-23 |
| 报告校验分级 | `render_report` 收窄阻断为「clients 非空数组 + 无 Jinja 残留 + 无 CSS 泄露」，字段齐全/密度/工具名泄漏降级为警告（消除打地鼠循环）；字段清单以 `schemas/report_schema.json` 为单一事实来源，校验器/参考文档/模板注释三者不再各自维护一份（此前 market_size/position 新旧格式、data_date/score/rank 三处漂移） | 用户决策 2026-08-24 |
| 报告数据端归一化 | LLM 产出的报告 JSON 形状不稳定（平铺字符串 / 错位字段名 / list 当 HTML 直出 / cover·appendix 缺字段 / 顶层非对象），在 `render_report` 渲染前经 `normalize_report` 统一转成模板 `cfr.html` 期望的 V5 结构化形态：字符串→结构化、list/dict→HTML 片段；缺失内容用「P1 数据受限」显式占位，消除 `[{'...'}]` repr 泄漏与大片空白。模板为唯一契约，对已结构化数据幂等，`main()` 与 `render()` 均先归一化。**全文件安全检查**：`_load_json_file` 拦截顶层非对象 JSON（argv/stdin 文件路径）；`normalize_report` 对非 dict 入参返回空对象；保证 cover/appendix 为 dict、appendix.version 缺省 V1；`main()` 输出文件名 `.get()` 兜底——渲染成功后文件名不再因缺字段抛 KeyError 丢弃整份报告（实测修复 2026-08-24）。配套单测 `tests/unit/test_report_normalize.py` | 用户决策 2026-08-24，归一化收敛于渲染前单点，不向模板扩散 if-elif（OCP） |
| 脚本失败诊断 | 脚本契约错误信息走 stdout JSON，broker 失败时透出 stdout 错误载荷（回落 stderr 尾部、再回落退出码占位），避免模型只见「退出码非 0」 | 实测修复 2026-08-23 |
| 持久化 | PostgreSQL + SQLAlchemy(async) + Alembic；迁移唯一通道（改模型 → `autogenerate` → `upgrade`）；引擎连接按会话即开即关（NullPool） | 用户决策 2026-08，CLAUDE.md §1 |
| 对话历史落库 | conversations 会话头 + messages 回合明细（query/answer/thinking 一行，usage 聚合到回合）；`ConversationService.record_turn` 回合结束单次落库，**DB 降级内部消化**（舱壁：失败记日志返回 bool，路由无 try/except、无 DB 感知）；首回合会话行由 record_turn 内部 upsert（name=截断首条 query，续聊保留）；会话接口 `GET /conversations`、`/messages`、`DELETE /conversations/{id}`（**软删除**标记独立 `is_delete=true`，业务状态 status 不被覆盖、行与 token 保留、仅列表隐藏、不可续聊；释放内存会话/运行时，两者皆无 → 404） | 用户决策 2026-08，评审采纳 |
| 账号认证 | accounts 表按用户 DDL（`id uuid DEFAULT uuid_generate_v4()` 需 pgcrypto、phone 索引、username 唯一索引、`is_system` 标注超级用户）；手机号+密码登录，密码存 **Argon2id PHC 自含编码**（参数 time_cost=3 / memory_cost=65536 / parallelism=4，CPU 密集经 anyio 线程池，无单独盐列）；会话用 **JWT HS256**（sub=account_id，密钥必须环境注入缺失即 ConfigError）；**无注册接口**，用户经 `python -m app.services.auth_provision` CLI 预置；认证恒启用无开关；个人接口 `/users/me`（查询）、`/users/me/usage`（用量）、`PATCH /users/me`（昵称）、`/users/me/avatar`（头像）、`/users/me/password`（改密码**必须原密码**）、`/users/me/avatar-config`（头像约束）；`GET /users`（超级用户）全量用量。头像约束严于通用上传：仅图片扩展名 + magic bytes 内容校验 + ≤2 MiB + 边长 32~512px（显示目标：侧栏 32px / 资料弹窗 ~96px 圆形），阈值配置驱动 | 用户决策 2026-08-28 / 2026-08-29 |
| 公司统一登录（elecnest SSO） | 与手机号+密码并列的登录来源：`POST /auth/login/elecnest`（body `{token, uid}`）→ `ElecnestSSOClient` 调 `ELECNEST_GET_USER_INFO_URL`（默认 `https://id.elecnest.cn/api/login/getUserInfo`，`GET token+uid`）换用户资料（昵称缺失回退用户名，`data` 为空即 401）→ `AuthService.login_with_elecnest` 按 `elecnest_uid` **find-or-create** 账号并标 `user_type=elecnest` → 签发令牌对。`accounts` 加 `elecnest_uid`（对方主键 uid 的字符串，唯一索引）+ `user_type`（默认 password）；`httpx.AsyncClient` 由容器注入（DIP，CLAUDE.md §13.2），开关默认开启（2026-08-29 由默认关闭改为默认开启），关闭时返回 400；既有账号不迁移保持 password | 用户决策 2026-08-29 |
| 登录会话层（Redis 权威 + 刷新令牌） | 登录签发「访问令牌（JWT，exp= `auth_access_token_ttl_seconds` 24h）+ 刷新令牌（`secrets.token_urlsafe(32)` 不透明随机串，`auth_refresh_token_ttl_seconds` 7d）」写入 Redis 会话层（`app/services/auth_session.py`，key `auth:access\|refresh:{sha256(token)}` = account_id，TTL 以 Redis 为准）。**Redis 权威**：`AuthService.validate_session` 每请求校验 JWT + Redis 访问会话存在，key 缺失即 401（即使 JWT 未过期）；`POST /auth/refresh` **轮换制**续期（先作废旧刷新令牌防重用，返回新令牌对）；`POST /auth/logout` 同时作废访问+刷新会话（DEL 幂等 204）。**Fail-closed**：任何 RedisError 一律转 401，不泄露内部细节；`redis_enabled=false` 降级纯 JWT——访问令牌不校验、刷新令牌不可用（容器启动告警）。配置 `AUTH_ACCESS_TOKEN_TTL_SECONDS` / `AUTH_REFRESH_TOKEN_TTL_SECONDS` 取代原 `JWT_EXPIRES_MINUTES` | 用户决策 2026-08-29 |
| 数据按账号隔离 | conversations.`from_account_id` + messages/upload_files/dedup_clues.`created_by`（varchar(36) 存 uuid 文本、无外键，平台惯例）；会话列表/消息/删除按账号过滤，跨账号 404；upload_files 预览**保持全局**（file_id 不可猜测）；dedup_clues 主键改 **(created_by, clue_id)** 按账号隔离，消除「两账号同日同产品生成相同 clue_id 互相覆盖」冲突；token 用量按 created_by **聚合 messages**（无汇总表，读时 SUM） | 用户决策 2026-08-28 |
| usage 防腐层 | `StreamParser` 把三种提供方缓存字段统一为平台标准（OpenAI `prompt_tokens_details.cached_tokens` / DeepSeek `prompt_cache_hit_tokens` / Anthropic `cache_read_input_tokens`+`cache_creation_input_tokens` → cached_read/cached_write）；`UsageAggregator` 回合聚合，Runner 各 LLM 调用点只调 `add()`，修复「后一次覆盖前一次」；DoneEvent 事件驱动携带聚合 usage + provider/model，消费方（路由/未来计费）只监听事件 | 评审采纳 |
| 文件系统 | `upload_files` 多消费方共享注册表（agent 产物 / 用户上传 / 知识库），**删 session/agent 强绑定**，`created_by_role` 宽松消费方标识，`used`/`used_at` 强制标注使用状态供清理；`/files` API：`GET /files/upload`（上传限制配置）、`POST /files/upload`（字节上传，校验大小+扩展名）、`GET /files/{file_id}/preview`（按 record id 流式 inline 预览，预览即标记 used）；`FileService`（register 磁盘产物 / upload 字节上传 / get_content_stream_by_id 预览） | 用户决策 2026-08 |
| 去重历史 | 结构化状态入 PG `dedup_clues`，脚本改纯计算：平台注入 `history`、add 模式经 `_upsert` 回写（声明 `history_store: true`） | 用户决策 2026-08 |
| 目录结构 | 技能包三级 `agents/{agent}/{skill}`（去掉 skills/ 壳与 shared/）；工作区 `workspaces/{agent}` 按 agent 键控、跨会话共享，会话删除不再清工作区 | 用户决策 2026-08 |
| 目录分层 | 业务服务统一收拢 `app/services/`（conversations/files/workspace/auth + auth_security/auth_provision），持久化仓库统一收拢 `app/repositories/`（dedup），跨边界 DTO 统一 `app/schemas/`，认证 FastAPI 依赖入 `app/api/deps.py`；删除散落的 feature 包（conversations/files/workspace/auth/dedup） | 用户决策 2026-08-28 |
| DB 连接地址 | 默认 URL 用 `127.0.0.1` 而非 `localhost`（Windows + Docker 下 localhost 先解析 IPv6 `::1`，回环转发超时 ~21s） | 实测修复 |
| 门禁执行 | 有校验器的门禁注册为脚本工具 `…script.gate_<id>`，tool_node 写 gate_status | graph-runtime-spec §6 |
| 审批 | 已整体移除：无审批节点 / 事件 / 接口 / 策略，工具调用直接执行 | 用户决策 2026-08 |
| 对话输出 | chat-messages 契约：`POST /chat-messages`，`response_mode=streaming` 走 SSE（`event` 判别帧，message/message_end/thinking_started/thinking_delta/thinking_ended/ping/error，无 `[DONE]`），`blocking` 返回 JSON；typewriter 节流 + 有界队列背压；思考经 `thinking_*` 帧独立暴露（不进 `message.answer`），供前端渲染 DeepSeek 式思考分区 | 用户决策 2026-08 |
| emitter | 单协程 tick 循环（嵌套任务组在父作用域取消时本机 anyio/asyncio 会死锁，流尾挂起） | 实测修复 |
| 后台热重载任务 | 单常驻协程 + CancelScope 宿主任务（`asyncio.create_task`），不用跨 startup/shutdown 常驻的 anyio task group：任务组跨任务退出报 cancel-scope 跨任务错误（pytest-asyncio 生成器 fixture setup/teardown 分任务），嵌套任务组宿主取消时死锁 | 实测修复 |
| 配置 | `pydantic-settings` 唯一入口，无硬编码 URL/密钥/阈值；env 白名单透传 | CLAUDE.md §5 |
| 生命周期 | 类式异步上下文管理器（`__aenter__` / `__aexit__`），禁用 `@asynccontextmanager` | CLAUDE.md §4 |
| 基础设施扩展化 | 外部能力（logging/db/storage/redis/mcp/llm）以扩展模块统一加载：`app/extensions/ext_*.py` 各暴露 `is_enabled()` / `init_app(app)` / `startup(app)` / `shutdown(app)`，`EXTENSIONS` 有序元组 + `initialize_extensions` 加载器按序启停（logging 最先）；配置开关 `{module}_enabled`（扩展经 `active_settings()` 读当前应用配置）；共享日志内核在 `app/kernel/logging.py`（脱敏/trace/模块级别）；跨切面 HTTP 关注点（全局异常 + 请求日志）落中间件（`app/middleware/`），替代内联 `@app.exception_handler`；领域服务（services/registry/runtime）留容器层经扩展访问器取客户端，容器瘦身为编排器 | 用户决策 2026-08，可插拔 / 统一加载 |

## 技术债（演进方向）

1. **messages 单行拍平**：query/answer/thinking 同行耦合「一问一答」范式；工具调用明细
   （ToolCalls/结果）不持久化。演进方向：role-based 消息流（message_id, conversation_id,
   role, content, parent_id）或事件溯源，以支持多 Agent 协作 / 系统主动触达 / 多工具分发。
2. **SessionStore 纯内存态**：内存是会话流转的唯一事实来源，DB 仅为只读审计 —— 单机 P1
   妥协。演进方向：对齐 LangGraph Checkpointer / Redis 持久化，消除「双写/脑裂」并支持
   水平扩展（多 Pod 路由到新节点不丢状态）。

## 主流程

`POST /chat-messages` → `conversation_id` 空串自动创建会话（续聊带上即复用）→
`response_mode=streaming` 开 SSE / `blocking` 返回 JSON → 图执行（解析助手 → 解析技能 →
装配 → 推理 ⇄ 工具）→ 收尾 emit done → 流尾显式取消 emitter。会话 ID 经响应头
`X-Conversation-Id` 与消息体返回。

产物：脚本执行前后扫描工作区，新增/变化文件自动登记，`GET /sessions/{sid}/artifacts/{aid}` 下载
（归属校验 + `Content-Disposition: attachment` + `nosniff`）。

## 运行方式

- 依赖：`uv sync`
- 启动 PostgreSQL：`docker compose up -d`（本地 PG；停止并清卷 `docker compose down -v`）
- 数据库迁移：`uv run alembic upgrade head`（改模型后 `uv run alembic revision --autogenerate -m "..."`）
- 开发服务器：`uv run uvicorn app.application:create_app --factory`（host/port 配置驱动；或 `uv run python -m app.main`）
- 校验：`uv run ruff check app tests && uv run ruff format --check app tests && uv run mypy app`
- 测试：`uv run pytest`（135 收集；测试四层结构 `tests/{unit,integration,http,e2e}`，按目录自动打标，可用
  `-m unit|integration|http|e2e` 过滤；unit/http 自包含可离线跑，integration 需要本地 PG（docker compose）
  供产物/去重历史用例，e2e 需要 127.0.0.1:8000 真服务（未启动自动 skip）；`addopts=-s` 放开捕获供
  e2e 打字机输出；无需 LLM/MCP 密钥）
- MCP 服务注册表：`config/mcp-servers.yaml`；LLM 提供方：`config/llm-providers.yaml`（只提交 example）
