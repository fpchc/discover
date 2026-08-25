# 多智能体承载平台架构快照

> P1 状态（2026-08）：12 步构建完成，eitia 智能体已迁移接入。对话接口为
> 对话接口 `POST /chat-messages`（会话自动创建）；审批机制、`/models`、`/agents`、
> 会话删除接口已按用户决策移除。脚本执行已去容器化（2026-08-21 用户决策）：
> 宿主 subprocess 本地直跑，Docker 不再是前置条件。持久化已入 PostgreSQL
> （SQLAlchemy async + Alembic）；产物走 Blob Engine（字节入存储层、元数据入库）；
> 去重历史入 `dedup_clues` 表（脚本纯计算）；技能包三级结构
> `agents/{agent}/{skill}`（无 skills/ 壳与 shared/），工作区 `workspaces/{agent}`
> 按 agent 键控、跨会话共享。全套测试 132 通过。
> 随代码演进持续同步；一次性任务报告不写入本文件。

## 分层与依赖方向

依赖只能自上而下，禁止反向 import。

```
L5  frontend/                  Chat UI（消费事件判别流）｜P1 未实现
L4  api/（controller）          FastAPI 路由；应用组装（application.py）、DI（container.py）、DTO（schemas/）随接入层；
                               中间件（middleware/：全局异常 + 请求日志）挂接入层；插件（plugins/：基础设施统一加载）由容器消费
L3  runtime/                   LangGraph 图：route_agent → route_skill → assemble
                                → agent ⇄ tool_node，generic_chat 兜底
L2  registry/ + tools/broker   装配层：清单解析/索引/热重载/装配；ToolBroker 工具目录与三级暴露
L1  llm/ + tools/(mcp|script)  LLM 客户端、MCP（Streamable HTTP）、宿主 subprocess 脚本执行器（本地直跑）
L0  db/ + storage/ + history/ + session/ + config/ + errors/ + protocol/
                               SQLAlchemy/ORM（PostgreSQL）、Blob 存储、去重历史仓库、
                               会话工作区与产物、配置载体、领域异常、事件发射器
```

L3 不直接认识 MCP 与脚本：只向 `ToolBroker` 要工具列表，向注册表要装配上下文。
图中无任何智能体名 / 技能名 / 工具名字面量——唯一耦合面是 `AGENT.md` / `SKILL.md` 清单。

## 关键设计决策

| 决策 | 结论 | 依据 |
|------|------|------|
| 包根名 | `app`（仓库根单层包，去除 src/ 包裹与 platform_engine 层；api/ 仅路由） | 用户决策 2026-08 |
| 业务流程载体 | 图只提供执行环境，流程知识写在智能体/技能清单正文 | graph-runtime-spec §1 |
| 两级路由 | 一级 `route_agent` → 二级 `route_skill`；会话内 `active_agent` 非空则跳过一级（重入保护） | graph-runtime-spec §9 |
| 技能耦合面 | 唯一耦合面是 `AGENT.md` / `SKILL.md` frontmatter | agent-package-spec |
| 工具命名空间 | MCP = `server.tool`；脚本 = `agent.skill.script.name`；元工具无前缀 | tool-broker-spec |
| 工具暴露 | 三级：Tier0 元工具 / Tier1 核心 / Tier2 懒加载 | tool-broker-spec |
| 脚本执行 | **P1 宿主 subprocess 直跑**（`sys.executable`，cwd=工作区，不做容器隔离）；脚本内禁止绝对路径字面量；对外开放脚本编辑后再评估轻量沙箱 | 用户决策 2026-08，script-sandbox-spec |
| 脚本路径归一 | `agents_root_dir` 在 `AgentRegistry` 归一为绝对路径（`Path.resolve()`）——技能目录 / 脚本宿主路径 / `SKILL_ROOT_DIR` 一律绝对；否则 subprocess cwd=工作区会把相对脚本路径按工作区解析而找不到（实测：dedup_manager "No such file or directory"） | 实测修复 2026-08-24 |
| 脚本入参契约 | 平台一律经 stdin 传 JSON，脚本须从 stdin 读入参；声明 `schema_path` 让模型可见正确参数约束。缺省 schema 只有 `input` 字段，多字段脚本（dedup/render/gate）必须补 schema，否则参数与脚本实际读取字段错位（实测：报告管线全部 `执行失败`） | 实测修复 2026-08-23 |
| 报告数据闭环 | AI 无写文件工具，报告 JSON 只能经 stdin 到达脚本；`render_report` 入参 **`data` 内联必填**（schema 移除 `input` 路径选项），渲染时把数据落盘 `output/report.json`；`gate_render_pass` 经 `report_json` 引用该落盘文件（`GateDeclaration.schema_path` 挂载校验器入参约束） | 实测修复 2026-08-23 |
| 报告校验分级 | `render_report` 收窄阻断为「clients 非空数组 + 无 Jinja 残留 + 无 CSS 泄露」，字段齐全/密度/工具名泄漏降级为警告（消除打地鼠循环）；字段清单以 `schemas/report_schema.json` 为单一事实来源，校验器/参考文档/模板注释三者不再各自维护一份（此前 market_size/eitia_position 新旧格式、data_date/score/rank 三处漂移） | 用户决策 2026-08-24 |
| 报告数据端归一化 | LLM 产出的报告 JSON 形状不稳定（平铺字符串 / 错位字段名 / list 当 HTML 直出 / cover·appendix 缺字段 / 顶层非对象），在 `render_report` 渲染前经 `normalize_report` 统一转成模板 `eitia-cfr.html` 期望的 V5 结构化形态：字符串→结构化、list/dict→HTML 片段；缺失内容用「P1 数据受限」显式占位，消除 `[{'...'}]` repr 泄漏与大片空白。模板为唯一契约，对已结构化数据幂等，`main()` 与 `render()` 均先归一化。**全文件安全检查**：`_load_json_file` 拦截顶层非对象 JSON（argv/stdin 文件路径）；`normalize_report` 对非 dict 入参返回空对象；保证 cover/appendix 为 dict、appendix.version 缺省 V1；`main()` 输出文件名 `.get()` 兜底——渲染成功后文件名不再因缺字段抛 KeyError 丢弃整份报告（实测修复 2026-08-24）。配套单测 `tests/unit/test_report_normalize.py` | 用户决策 2026-08-24，归一化收敛于渲染前单点，不向模板扩散 if-elif（OCP） |
| 脚本失败诊断 | 脚本契约错误信息走 stdout JSON，broker 失败时透出 stdout 错误载荷（回落 stderr 尾部、再回落退出码占位），避免模型只见「退出码非 0」 | 实测修复 2026-08-23 |
| 持久化 | PostgreSQL + SQLAlchemy(async) + Alembic；迁移唯一通道（改模型 → `autogenerate` → `upgrade`）；引擎连接按会话即开即关（NullPool） | 用户决策 2026-08，CLAUDE.md §1 |
| 文件存储 | Blob Engine：字节入存储层（`BaseStorage` + `LocalStorage`，UUID 扁平 `{uuid}.{ext}`），元数据 100% 入 `upload_files` 表；下载按 session 归属校验后流式回传 | 用户决策 2026-08 |
| 去重历史 | 结构化状态入 PG `dedup_clues`，脚本改纯计算：平台注入 `history`、add 模式经 `_upsert` 回写（声明 `history_store: true`） | 用户决策 2026-08 |
| 目录结构 | 技能包三级 `agents/{agent}/{skill}`（去掉 skills/ 壳与 shared/）；工作区 `workspaces/{agent}` 按 agent 键控、跨会话共享，会话删除不再清工作区 | 用户决策 2026-08 |
| DB 连接地址 | 默认 URL 用 `127.0.0.1` 而非 `localhost`（Windows + Docker 下 localhost 先解析 IPv6 `::1`，回环转发超时 ~21s） | 实测修复 |
| 门禁执行 | 有校验器的门禁注册为脚本工具 `…script.gate_<id>`，tool_node 写 gate_status | graph-runtime-spec §6 |
| 审批 | 已整体移除：无审批节点 / 事件 / 接口 / 策略，工具调用直接执行 | 用户决策 2026-08 |
| 对话输出 | chat-messages 契约：`POST /chat-messages`，`response_mode=streaming` 走 SSE（`event` 判别帧，message/message_end/thinking_started/thinking_delta/thinking_ended/ping/error，无 `[DONE]`），`blocking` 返回 JSON；typewriter 节流 + 有界队列背压；思考经 `thinking_*` 帧独立暴露（不进 `message.answer`），供前端渲染 DeepSeek 式思考分区 | 用户决策 2026-08 |
| emitter | 单协程 tick 循环（嵌套任务组在父作用域取消时本机 anyio/asyncio 会死锁，流尾挂起） | 实测修复 |
| 后台热重载任务 | 单常驻协程 + CancelScope 宿主任务（`asyncio.create_task`），不用跨 startup/shutdown 常驻的 anyio task group：任务组跨任务退出报 cancel-scope 跨任务错误（pytest-asyncio 生成器 fixture setup/teardown 分任务），嵌套任务组宿主取消时死锁 | 实测修复 |
| 配置 | `pydantic-settings` 唯一入口，无硬编码 URL/密钥/阈值；env 白名单透传 | CLAUDE.md §5 |
| 生命周期 | 类式异步上下文管理器（`__aenter__` / `__aexit__`），禁用 `@asynccontextmanager` | CLAUDE.md §4 |
| 基础设施插件化 | 外部能力（logging/db/storage/redis/mcp/llm）以插件统一加载：配置开关 `{plugin}_enabled` + 生命周期（startup/shutdown）+ 类型化客户端（`app/plugins/`，注册顺序即启动顺序，logging 最先）；跨切面 HTTP 关注点（全局异常 + 请求日志）落中间件（`app/middleware/`），替代内联 `@app.exception_handler`；领域服务（session/registry/runtime）留容器层从插件取客户端，容器瘦身为编排器 | 用户决策 2026-08，可插拔 / 统一加载 |

## 主流程

`POST /chat-messages` → `conversation_id` 空串自动创建会话（续聊带上即复用）→
`response_mode=streaming` 开 SSE / `blocking` 返回 JSON → 图执行（一级路由 → 二级路由 →
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
