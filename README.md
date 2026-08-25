# discover

多智能体承载平台全栈仓库。前端为 ChatGPT 风格单页对话应用，后端为多智能体承载平台
（FastAPI + LangGraph + PostgreSQL），部署资产统一整合在仓库根。

## 目录结构

```text
discover_backend/            多智能体承载平台（FastAPI / LangGraph / SQLAlchemy async）
├── Dockerfile               后端镜像（uv + Alembic + uvicorn）
└── .dockerignore
discover_frontend/           Chat UI（Vue 3 + Vite + Element Plus）
├── Dockerfile               前端多阶段镜像（dev / build / runtime-nginx）
├── nginx.conf               SSE 反代模板（envsubst）
├── security-headers.conf    CSP 等安全头
└── .dockerignore
docker-compose.base.yml      后端公共 environment（dev / prod / test 以 extends 复用）
docker-compose.yml           dev 编排（后端热重载 + 前端热更新；不内置 postgres）
docker-compose.prod.yml      prod 编排（postgres + nginx 反代，8080）
docker-compose.test.yml      test 编排（postgres + nginx 反代，8081）
```

## 一键启动（Docker）

三套 compose 均为一键拉起全栈：`backend` + `frontend`；prod / test 另带 `postgres`，
dev 不内置 postgres（数据库连接走热挂载 `discover_backend/.env` 配置的外部库）。

```bash
# dev：前端 5173（Vite 热更新）/ 后端 8000（--reload 热重载）
docker compose up --build

# prod：前端 8080（nginx 静态服务 + /api 反代）
docker compose -f docker-compose.prod.yml up --build -d

# test：前端 8081（VITE_APP_ENV=test 构建）
docker compose -f docker-compose.test.yml up --build -d

# 停止 / 清库
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml down -v   # 连同卷一并清除
```

### 服务关系

- **postgres**（prod / test）：本地数据库，`DB_*` 环境变量指向该服务（compose 内 `postgres` 服务名）；
  dev 不内置 postgres，`DB_*` 由热挂载的 `discover_backend/.env` 提供。
- **backend**：镜像启动先 `alembic upgrade head` 应用迁移，再起 uvicorn；运行时可写目录
  `storage/` / `logs/` / `workspaces/` 在 dev 直接落在宿主机 `discover_backend/`，在 prod/test 用命名卷持久化。
- **frontend**：
  - dev：源码热挂载 + Vite dev server，`/api` 反代到 `http://backend:8000`（免 CORS）；
  - prod / test：多阶段构建产物由 nginx 托管，`/api` 反向代理到 backend 服务（SSE 关缓冲）。

### 配置注入

- 后端公共参数（含 `LLM_API_KEY` / `ALIBABA_SEARCH_TOKEN` 空占位）集中在 `docker-compose.base.yml` 的
  `backend-base.environment`，三套 compose 以 `extends` 复用，一处修改三处生效；真实密钥直接在该文件填入
  （仓库只提交 `.env.example`，真实密钥不入库）。
- `DB_*` 按环境各自声明：prod / test 指向 compose 内 postgres；dev 不内置 postgres，走热挂载 `discover_backend/.env`。
- nginx 反代目标经 `BACKEND_PROXY_PASS` 注入（默认 `http://backend:8000`）。

## 本地开发（不经 Docker）

- 后端：`cd discover_backend && uv sync && uv run uvicorn platform_engine.api.app:create_app --factory --reload`
  （依赖 PostgreSQL，连接配置见 `discover_backend/.env`）。
- 前端：`cd discover_frontend && pnpm install && pnpm dev`（`/api` 默认代理到 `http://127.0.0.1:8000`）。

> 各子项目详细文档：`discover_backend/README.md`、`discover_frontend/README.md`。
