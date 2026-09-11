# 全局协作与红线约束

> `AGENTS.md` 与 `CLAUDE.md` 是面向 Codex / Claude 的等价入口，内容必须同步。
> 本文件只保留跨任务长期有效的规则；专项规范放 `specs/*.md`，当前架构事实放 `docs/*.md`。

## 0. 规则层级与简化机制

优先级从高到低：平台安全与工具约束 → 本文件硬约束 → 约束范围内的用户当前明确要求 → 当前任务匹配的专项规范 → `docs` 架构记忆 → 设计默认值。低优先级内容不得覆盖高优先级规则。

仅第 5 节“设计默认值”允许因避免过度设计而简化，并须在代码处标注 `# pragma: 简化 — <原因>`。该标记不得用于绕过安全、类型、异步、配置、数据库或外部 I/O 红线。

## 1. 固定技术栈

| 技术 | 硬约束 |
|---|---|
| FastAPI | 路由、依赖、Provider、DB 调用一律 `async def` |
| LangGraph | 业务流程用状态机（节点 + 条件边）编排，不把流程控制写进自然语言提示词 |
| Pydantic v2 / pydantic-settings | 数据、配置、跨边界模型统一使用 `BaseModel` / `BaseSettings`；序列化使用 `model_dump` / `model_validate` |
| httpx.AsyncClient | 外部 HTTP 调用的唯一出口 |
| SQLAlchemy 2.0 async | 持久化使用 ORM、`AsyncSession` 与异步驱动；禁止同步 engine 和裸 SQL 直连 |
| Alembic | 数据库迁移唯一通道；禁止手工修改数据库结构 |
| asyncpg | PostgreSQL URL 固定使用 `postgresql+asyncpg://` |
| pytest / mypy | 唯一测试框架与类型检查基线 |

不得新增未列出的同类替代库。

## 2. Python、类型与模型边界

- Python `>= 3.12`；使用 `X | None`、`list[T]`、`dict[K, V]` 与 `type` 别名。
- 所有函数和方法的每个参数、返回值必须显式标注，`self` / `cls` 除外；异步生成器标注 `AsyncGenerator[T, None]` 或 `AsyncIterator[T]`。
- 禁止用 `Any` 规避检查。仅无类型第三方库边界允许使用，并标注 `# pragma: 简化 — <原因>`。
- `# type: ignore` 必须包含错误码与原因，例如 `# type: ignore[arg-type]  # 原因`。
- 抽象接口使用 `Protocol` 或 `ABC`，确保可由 mypy 静态检查。
- 配置使用 `BaseSettings`；请求、响应、DTO、事件、outcome、持久化对象和任务负载使用 `BaseModel`。
- `@dataclass` 仅用于纯内部不可变值对象或运行时句柄，并标注 `# pragma: 简化 — <原因>`；不得跨生命周期边界。

## 3. 异步、并发与外部资源

- async 路径严禁阻塞式同步 I/O，包括文件读写、`time.sleep`、同步 DB 驱动和同步 SDK；必要时使用 `anyio.to_thread.run_sync`。
- 禁止 `contextlib.asynccontextmanager`；生命周期和自定义异步上下文管理器使用类式 `__aenter__` / `__aexit__`。
- 并发任务使用 anyio task group；禁止创建未受生命周期管理的裸任务。
- 外部客户端、`AsyncSession`、存储及第三方服务必须通过 FastAPI 依赖层或构造函数注入；业务逻辑内部不得直接实例化。
- 禁止模块级可变容器充当跨请求缓存或共享状态；共享资源必须有显式生命周期和并发保护。

## 4. 配置与敏感信息

- 全局配置统一使用 pydantic-settings；扩展开关命名为 `{module_name}_enabled: bool`。
- URL、密钥、路径、模型名、阈值、超时和重试次数不得硬编码，统一进入配置。
- 仓库只允许提交 `.env.example`；禁止读取或提交 `.env`、`*.pem`、`*.key` 等敏感文件。
- 认证信息、完整请求体和敏感数据不得出现在日志、异常或用户可见输出中。

## 5. 设计默认值

以“一个需求尽量只影响一个 feature 边界”为判据，优先高内聚、低耦合，而不是机械增加抽象。

- 函数 / 方法原则上不超过 30 行、参数不超过 5 个；主函数只编排，细节下沉。
- 同一维度分支超过 3 个时，优先策略表、注册表或配置驱动。
- 重写不得收窄输入、放宽返回类型或新增父接口未声明的异常。
- 避免超过两跳的链式访问；通过公开方法隐藏内部结构。
- 单个 `Protocol` / `ABC` 原则上不超过 5 个方法；按调用方拆分接口。
- Service 构造函数只依赖抽象；核心业务不依赖 FastAPI、SQLAlchemy ORM 或具体第三方实现。
- 继承深度不超过 2 层；复用优先组合与注入。
- 强相关的路由、Service、Schema、ORM 模型和测试就近放在同一 feature 包；对外通过 `__init__.py` 的 `__all__` 暴露 Facade。
- 文件尽量不超过 300 行，超过 500 行必须拆分；拆分按修改理由，而不是按代码类型机械横切。

## 6. 仓库与文件访问边界

- 所有读取、搜索、命令和写入只允许发生在当前仓库目录内；禁止访问桌面、用户目录、剪贴板、临时目录等仓库外位置。
- 禁止读取构建产物和缓存：`venv/`、`.venv/`、`node_modules/`、`__pycache__/`、`.mypy_cache/` 等。
- 禁止读取 `.gitignore` 忽略的内容；工具无法自动过滤时，命令必须显式排除。
- `.claude/feature/` 与 `eitia-client-finder/` 是历史参考，仅在用户明确要求时读取。
- 不覆盖、不回滚用户已有改动；执行删除、重置、批量移动等破坏性操作前必须获得明确授权。

## 7. 任务行为与专项规范

- 未收到明确的“写代码 / 修改代码 / 生成代码”要求时，不得产生代码改动。
- 非骨架任务默认先说明方案再修改；用户已确认方案、给出明确实施步骤或要求直接修改时，不重复确认。
- 骨架生成必须给出完整实现，不使用省略占位。
- 开始任务前，仅加载与任务直接匹配的 `specs/*.md`；不批量加载全部专项规范。归属不明确时先读取 `specs/INDEX.md`，再选择具体规范。多个规范冲突时按第 0 节处理，并指出冲突。
- 新建专项规范前先检查是否已有同职责文件；一文件一职责，文件名使用 `kebab-case`，技术规范优先命名为 `*-spec.md`，开头必须写“适用场景 / 不适用场景 / 职责边界与权威来源”。

## 8. 测试与验证

- 测试只使用 pytest；文件命名 `test_*.py`，测试函数命名 `test_*`。
- 默认交付自检只运行无 DB 的 `tests/unit`，不得读取真实环境变量，也不得连接生产或开发数据库。
- 涉及 DB 的测试仅在用户明确要求且存在隔离测试环境时执行；必须使用隔离 fixture，禁止触碰真实数据。
- HTTP 测试使用 respx 或注入的 mock client，严禁真实网络请求。
- 时间、随机数与超时逻辑必须通过 Provider、freezegun 或 pytest-mock 固定，保证幂等。
- `tests/` 内允许局部放宽返回值注解和 mock 的 `Any`，但不得扩散到生产代码。

## 9. 架构记忆与交付

- `docs/ARCHITECTURE.md` 是当前架构与关键决策的事实源；`docs/MODULE_MAP.md` 是职责到路径的事实源。
- 只有代码结构、模块职责或关键设计决策发生变化时才更新 `docs`；一次性报告和进度记录不得写入。
- 修改 Python 后，交付前必须完成：变更文件 `ruff format`、`ruff check`、相关无 DB pytest、必要的 mypy 检查。
- 核心业务逻辑变更必须配套测试；确认无真实 HTTP、真实 DB、阻塞 I/O、硬编码配置和跨边界 dataclass。
- 仅文档修改不强制运行 Python 测试，但须检查链接、引用、重复规则和 `AGENTS.md` / `CLAUDE.md` 同步性。
