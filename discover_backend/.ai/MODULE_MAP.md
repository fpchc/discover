# 模块地图（职责 → 文件路径）

> 新增/删除模块文件后必须同步更新本表。P1 快照：2026-08。

## 基础层（L0）

| 职责 | 路径 |
|------|------|
| 全局配置（pydantic-settings） | `src/platform_engine/config/settings.py` |
| 注册表/配置 YAML 加载 | `src/platform_engine/config/loader.py` |
| 领域异常 + 错误分类 | `src/platform_engine/errors/base.py` |
| AgentEvent 事件模型 | `src/platform_engine/protocol/events.py` |
| QueueEmitter（seq/打字机/心跳/背压） | `src/platform_engine/protocol/emitter.py` |
| 事件/错误消息脱敏 | `src/platform_engine/protocol/sanitize.py` |
| 中文 grapheme 切分 | `src/platform_engine/protocol/graphemes.py` |

## 持久化层（L0，db）

| 职责 | 路径 |
|------|------|
| SQLAlchemy 声明式基类 + 命名约定 + UTC 时间 | `src/platform_engine/db/base.py` |
| 异步引擎 + 会话工厂（NullPool 即开即关） | `src/platform_engine/db/engine.py` |
| ORM 模型（upload_files / dedup_clues） | `src/platform_engine/db/models.py` |

## 存储层（L0，storage，Blob Engine）

| 职责 | 路径 |
|------|------|
| BaseStorage 抽象（save/load_once/load_stream/download/exists/delete/url/scan） | `src/platform_engine/storage/base.py` |
| LocalStorage（UUID 扁平、anyio 线程池） | `src/platform_engine/storage/local.py` |

## 历史仓库（L0，history）

| 职责 | 路径 |
|------|------|
| 去重历史注入/回写（dedup_clues 表，脚本纯计算契约） | `src/platform_engine/history/repo.py` |

## LLM 层（L1）

| 职责 | 路径 |
|------|------|
| LLM 客户端（httpx + 流式） | `src/platform_engine/llm/client.py` |
| 请求/响应/工具模型 | `src/platform_engine/llm/models.py` |
| 提供方注册表 + 别名解析 + 密钥解析 | `src/platform_engine/llm/providers.py` |
| 流式分块解析（Text/Thinking/ToolCalls/Finish） | `src/platform_engine/llm/stream_parser.py` |
| LLM 特定异常 | `src/platform_engine/llm/errors.py` |

## 会话层（L0/L1）

| 职责 | 路径 |
|------|------|
| 会话/产物模型 | `src/platform_engine/session/models.py` |
| 会话存储 | `src/platform_engine/session/store.py` |
| workspace 创建/路径校验/防穿越（按 agent 键控） | `src/platform_engine/session/workspace.py` |
| 产物登记（字节入存储层、元数据入库、下载归属） | `src/platform_engine/session/artifacts.py` |
| 会话服务门面 | `src/platform_engine/session/service.py` |

## 工具层（L1/L2）

| 职责 | 路径 |
|------|------|
| ToolBroker：激活、三级暴露、并发 | `src/platform_engine/tools/broker.py` |
| 工具描述/限定名/chat spec | `src/platform_engine/tools/descriptor.py` |
| MCP 客户端（Streamable HTTP JSON-RPC） | `src/platform_engine/tools/mcp_client.py` |
| MCP 进程/连接池（引用计数、空闲回收） | `src/platform_engine/tools/mcp_manager.py` |
| 脚本执行器（本地 subprocess、stdin/stdout、产物扫描） | `src/platform_engine/tools/script_executor.py` |

## 装配层（L2，registry）

| 职责 | 路径 |
|------|------|
| AGENT/SKILL 清单模型 | `src/platform_engine/registry/manifests.py` |
| 包扫描 + frontmatter 解析 + 加载期校验（绝对路径禁令） | `src/platform_engine/registry/loader.py` |
| 两级索引（智能体/技能） | `src/platform_engine/registry/index.py` |
| 技能装配（上下文注入 + 门禁脚本注册） | `src/platform_engine/registry/assemble.py` |
| 热重载（开关驱动、快照语义） | `src/platform_engine/registry/hot_reload.py` |
| 注册表门面 | `src/platform_engine/registry/registry.py` |

## 图运行时层（L3，runtime）

| 职责 | 路径 |
|------|------|
| GraphState / GateStatus / RouteDecision | `src/platform_engine/runtime/state.py` |
| 节点实现 + 单轮执行入口 + 上下文裁剪 | `src/platform_engine/runtime/runner.py` |
| LangGraph 拓扑构建 | `src/platform_engine/runtime/builder.py` |

## 接入层（L4，api）

| 职责 | 路径 |
|------|------|
| 应用工厂 + 生命周期 + 异常映射 | `src/platform_engine/api/app.py` |
| 服务容器 DI + startup/shutdown | `src/platform_engine/api/deps.py` |
| 请求/响应模型 | `src/platform_engine/api/models.py` |
| 对话接口（/chat-messages，SSE / blocking） | `src/platform_engine/api/routes_chat.py` |
| 产物下载（归属校验 + 安全头） | `src/platform_engine/api/routes_artifacts.py` |
| 对话控制台客户端（SSE 打字机渲染，多轮） | `src/platform_engine/console/chat.py` |

## 数据与配置（非代码）

| 内容 | 路径 |
|------|------|
| eitia 智能体包（三级结构：`agents/eitia/client-finder/`） | `agents/eitia/` |
| eitia 脚本入参约束（score/render/dedup/gate，模型可见参数 schema） | `agents/eitia/client-finder/schemas/` |
| eitia 报告数据契约单一事实来源（required_fields/optional/compat，驱动 render_report.check_completeness） | `agents/eitia/client-finder/schemas/report_schema.json` |
| eitia 脚本：评分 / 去重 / 渲染 / 门禁校验（stdin JSON 契约） | `agents/eitia/client-finder/scripts/` |
| 门禁声明入参约束（`GateDeclaration.schema_path` → 校验器脚本工具） | `src/platform_engine/registry/manifests.py` |
| 迁移源（只读历史参考） | `eitia-client-finder/` |
| MCP 服务注册表 | `config/mcp-servers.yaml`（example 可提交） |
| LLM 提供方注册表 | `config/llm-providers.yaml`（example 可提交） |
| 环境变量模板 | `.env.example` |
| 单元测试（无网络 / 无 DB） | `tests/unit/` |
| 集成测试（依赖本地 PostgreSQL） | `tests/integration/` |
| HTTP 接入层测试（TestClient 进程内 ASGI） | `tests/http/` |
| 端到端测试（需真服务 127.0.0.1:8000，未启动自动 skip） | `tests/e2e/` |
| 测试共享 fixture（make_test_app / make_client + 四层 marker 自动打标） | `tests/conftest.py` |
