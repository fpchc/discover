# CLAUDE.md — 全局红线约束

> 本文件只写全局硬约束。单项职责细则放 `.claude/commands/*.md`，架构记忆放 `.ai/*.md`。
> **逃逸机制**：本文件所有规则在严格遵循会导致过度设计时，允许实用主义简化，但必须在代码处标注
> `# pragma: 简化 — <原因>`。无标注的偏离视为违规。

## 1. 技术栈（固定，不可替换，不可新增未列出的同类库）

| 技术 | 约束 |
|---|---|
| **FastAPI** | 路由 / 依赖 / Provider / DB 调用一律 `async def` |
| **LangGraph** | 业务流程用状态机（节点 + 条件边）编排，禁止把流程控制写成自然语言提示词 |
| **Pydantic v2**（含 `pydantic-settings`） | 数据 / 配置 / 跨边界模型统一 `BaseModel`，序列化走 `model_dump` / `model_validate` |
| **httpx.AsyncClient** | 所有外部 HTTP 调用的唯一出口 |
| **SQLAlchemy 2.0**（async） | 持久化统一走 ORM（`AsyncSession` + async 驱动）；禁止同步 engine / 裸 SQL 直连 |
| **Alembic** | 数据库迁移唯一通道：改模型 → `alembic revision --autogenerate` → `upgrade`，禁止手工改库 |
| **asyncpg** | PostgreSQL 异步驱动，URL 协议固定 `postgresql+asyncpg://` |
| **mypy** | 类型检查基线，见第 2 节 |

## 2. Python 语言与类型

* Python `>= 3.12`；新式注解 `X | None`、`list[T]`、`dict[K, V]`，别名用 `type` 语句。
* **全量注解**：所有函数与方法（含私有、工厂、回调、测试辅助）的每个参数和返回值都必须显式标注；`self` / `cls` 除外。禁止依赖 IDE、调用方或默认值推断。
* **禁止用 `Any` 规避检查**：配置、会话、客户端等对象必须标注具体类型（如 `settings: Settings`）。仅在与无类型第三方库交互的边界允许 `Any`，且需 `# pragma: 简化 — <原因>`。
* **异步返回值**：异步生成器标 `AsyncGenerator[T, None]` 或 `AsyncIterator[T]`；普通 `async def` 标实际返回类型，不得省略。
* **抽象接口**：用 `abc.ABC` 或 `typing.Protocol`，保证 mypy 可静态检查。
* **`# type: ignore` 必须带错误码和原因**（`# type: ignore[arg-type]  # 原因`），裸 ignore 视为违规。

## 3. 数据模型边界

| 用途 | 载体 |
|---|---|
| 配置载体 | `BaseSettings` |
| 跨生命周期边界的 DTO / 事件 / outcome | `BaseModel` |
| 持久化对象、请求 / 响应模型、任务队列负载 | `BaseModel` |
| 纯内部不可变值对象、运行时句柄 | 允许 `@dataclass`，需 `# pragma: 简化 — <原因>` |

新增模型默认 pydantic。跨边界模型误用 `@dataclass` 视为违规。

## 4. 异步与并发

* `async` 路径内严禁阻塞式同步 I/O（含文件读写、`time.sleep`、同步 DB 驱动、同步 SDK）；必须调用同步库时用 `anyio.to_thread.run_sync` 包装。
* 禁止 `contextlib.asynccontextmanager`（ruff `TID251` 拦截）。应用生命周期与自定义异步上下文管理器一律类式实现（`__aenter__` / `__aexit__`）。
* 并发任务用 `anyio` task group，禁止裸 `asyncio.create_task` 后不管理生命周期。

## 5. 配置驱动

* 全局配置走 `pydantic-settings`；扩展启用开关统一命名 `{module_name}_enabled: bool`。
* 代码中禁止硬编码 URL / 密钥 / 阈值 / 超时 / 重试次数 / 模型名，一律进配置。
* 仓库只允许提交 `.env.example`。

## 6. 设计原则（SOLID + CARP）

以下规则为可判定基线，违反需 `# pragma: 简化` 标注原因。

| # | 原则 | 可判定规则 |
|---|---|---|
| 1 | **SRP** 单一职责 | 函数 ≤ 30 行、参数 ≤ 5 个；主函数只做编排，细节下沉为私有子函数 |
| 2 | **OCP** 开闭 | 同一维度的分支超过 3 个 → 改用策略表 / 注册表 / 配置驱动；禁止无限延伸的 if-elif-else |
| 3 | **LSP** 里氏替换 | 重写方法不收窄入参、不放宽返回类型、不新增父类未声明的异常 |
| 4 | **LoD** 迪米特 | 链式访问最多 2 跳；`a.b.c.d` 一律封装为方法暴露 |
| 5 | **ISP** 接口隔离 | 单个 ABC / Protocol 方法数 ≤ 5；按调用方需求拆分，不定义大而全接口 |
| 6 | **DIP** 依赖倒置 | Service 构造函数只接受抽象 / Protocol 类型；具体实现在 FastAPI 依赖层组装，禁止在 Service 内 `new` 底层工具类 |
| 7 | **CARP** 合成复用 | 继承深度 ≤ 2 层；为复用而继承一律改为组合 + 注入 |

## 7. 目录职责与边界

| 路径 | 职责 |
|---|---|
| `CLAUDE.md` | 全局红线约束（本文件） |
| `.claude/commands/*.md` | 单项职责规范，一文件一职责，LLM 按任务内容自行识别加载 |
| `.ai/*.md` | 模型记忆：架构快照、模块路径映射 |
| `.claude/feature/` | 历史需求参考，只读，见第 9 节 |

## 8. `.ai` 记忆维护

* `.ai/ARCHITECTURE.md`：架构快照 + 关键设计决策，代码结构变化后同步更新。
* `.ai/MODULE_MAP.md`：职责 → 文件路径速查表，新增 / 删除模块文件后同步更新。
* 一次性任务报告、进度记录不属于记忆，不写入 `.ai`。

## 9. 禁止扫描 / 读取路径

* 敏感文件：`.env`、`*.pem`、`*.key`
* 构建产物：`venv/`、`.venv/`、`node_modules/`、`__pycache__/`、`.mypy_cache/`
* `.gitignore` 忽略的全部内容
* 历史参考：`.claude/feature/`、`eitia-client-finder/` —— 仅用户明确提及时才读取

## 10. 行为约束

* 未收到明确的「写代码 / 修改代码 / 生成代码」指令，严禁输出任何代码改动。
* 非骨架任务：修改前必须先与用户确认方案。
* 骨架生成：必须输出完整代码，禁止省略。

## 11. `.claude/commands` 编写规范

* 新建前先检查是否已有同职责文件，避免重复。
* 一个 command 只讲一个职责，命名 `kebab-case.md`。
* 文件开头必须写明「适用场景 / 何时触发」，供 LLM 按任务内容匹配。

## 12. 交付前自检清单

改动 Python 代码后，未全部通过不得交付：

- [ ] 变更文件 `ruff check` 与 `ruff format` 通过
- [ ] 变更文件 `mypy` 通过，无未注解签名、无裸 `# type: ignore`
- [ ] 无跨边界 `@dataclass`（第 3 节）
- [ ] `async` 路径无阻塞 I/O（第 4 节）
- [ ] 无硬编码 URL / 密钥 / 阈值（第 5 节）
- [ ] 偏离设计原则处均有 `# pragma: 简化 — <原因>`
- [ ] 代码结构有变化时已更新 `.ai/ARCHITECTURE.md` 与 `.ai/MODULE_MAP.md`
