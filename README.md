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
docker-compose.yml           dev 全栈编排（postgres + 后端热重载 + 前端热更新）
docker-compose.prod.yml      prod 全栈编排（nginx 反代，8080）
docker-compose.test.yml      test 全栈编排（nginx 反代，8081）
```

## 一键启动（Docker）

三套 compose 均为一键拉起全栈：`postgres` + `backend` + `frontend`。

```bash
# dev：前端 5173（Vite 热更新）/ 后端 8000（--reload 热重载）/ postgres 5432
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

- **postgres**：本地开发数据库，`DB_*` 环境变量指向该服务（compose 内 `postgres` 服务名）。
- **backend**：镜像启动先 `alembic upgrade head` 应用迁移，再起 uvicorn；运行时可写目录
  `storage/` / `logs/` / `workspaces/` 在 dev 直接落在宿主机 `discover_backend/`，在 prod/test 用命名卷持久化。
- **frontend**：
  - dev：源码热挂载 + Vite dev server，`/api` 反代到 `http://backend:8000`（免 CORS）；
  - prod / test：多阶段构建产物由 nginx 托管，`/api` 反向代理到 backend 服务（SSE 关缓冲）。

### 配置注入

- 后端密钥与其余配置（LLM API Key、搜索 Token 等）走宿主机 `discover_backend/.env`（compose `env_file`，可缺省）；
  仓库只提交 `.env.example`，真实 `.env` 不入库。
- 数据库连接由 compose `environment` 覆盖为本地 postgres；如需连远程库，改 `DB_HOST` 等即可。
- nginx 反代目标经 `BACKEND_PROXY_PASS` 注入（默认 `http://backend:8000`）。

## 本地开发（不经 Docker）

- 后端：`cd discover_backend && uv sync && uv run uvicorn platform_engine.api.app:create_app --factory --reload`
  （依赖本地 PostgreSQL，可先 `docker compose up -d postgres` 起根级 compose 里的 postgres）。
- 前端：`cd discover_frontend && pnpm install && pnpm dev`（`/api` 默认代理到 `http://127.0.0.1:8000`）。

> 各子项目详细文档：`discover_backend/README.md`、`discover_frontend/README.md`。
