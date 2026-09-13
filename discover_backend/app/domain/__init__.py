"""DDD 领域层：只承载业务（CRUD）侧的领域词汇与端口。

Agent System 的三根核心边界不在这里——见顶层 `app/llm/`（L）、
`app/harness/`（H）、`app/environment/`（E）。本层只保留业务承载：
会话（conversation）、文件（file）、身份（identity）。

**零框架、零 I/O**：不 import FastAPI / SQLAlchemy / httpx / redis / anyio，
不直接访问数据库、存储、子进程或外部 HTTP。具体实现由 `infrastructure`
提供，用例编排由 `application` 提供，组合根负责装配。
"""

__all__: list[str] = []
