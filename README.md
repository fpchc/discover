# discover

多智能体承载平台全栈仓库。前端为 ChatGPT 风格单页对话应用，后端为多智能体承载平台
（FastAPI + LangGraph + PostgreSQL），部署资产统一整合在仓库根。

## 目录结构

```text
discover_backend/            多智能体承载平台（FastAPI / LangGraph / SQLAlchemy async）
├── Dockerfile               后端镜像（uv + Alembic + uvicorn）
└── .dockerignore
discover_frontend/           Chat UI（Nuxt 4 SPA + Element Plus）
├── Dockerfile               前端多阶段镜像（dev / build / runtime-nginx）
├── nuxt.config.ts           Nuxt 4 配置（SPA 固定 / nitro devProxy / 模块装配）
├── nginx.conf               SSE 反代模板（envsubst）
├── security-headers.conf    CSP 等安全头
└── .dockerignore
docker-compose.yml           dev 编排（后端热重载 + 前端热更新；不内置 postgres）
docker-compose.prod.yml      prod 编排（postgres + nginx 反代，8080）
docker-compose.test.yml      test 编排（nginx 反代，9003；域名 research.elecnest.cn 经宿主机网关接入）
deploy/                      部署物统一管理（网关反代、部署脚本、配置归属说明，见 deploy/README.md）
```

## 一键启动（Docker）

三套 compose 均为一键拉起全栈：`backend` + `frontend`。数据库：prod 内置 `postgres`；
test 与 dev 不内置——test 连远程库（默认 `175.178.45.21`，可用根目录 `.env` 覆盖 `DB_*`），
dev 走热挂载 `discover_backend/.env` 配置的外部库。

```bash
# dev：前端 3000（Nuxt dev 热更新）/ 后端 8000（--reload 热重载）
docker compose up --build

# prod：前端 8080（nginx 静态服务 + /api 反代）
docker compose -f docker-compose.prod.yml up --build -d

# test：IP:9003；域名 research.elecnest.cn 经宿主机 nginx 网关反代到 9003（VITE_APP_ENV=test 构建）
docker compose -f docker-compose.test.yml up --build -d

# 服务器端完整部署步骤见下方「测试环境部署（test）」；部署资产集中在 deploy/（deploy/scripts/deploy-test.sh、deploy/nginx/）

# 停止 / 清库
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml down -v   # 连同卷一并清除
```

### 服务关系

- **postgres**（prod）：本地数据库，`DB_*` 环境变量指向该服务（compose 内 `postgres` 服务名）；
  test / dev 不内置 postgres——test 默认连远程库 `175.178.45.21`（根目录 `.env` 可覆盖 `DB_*`），
  dev 的 `DB_*` 由热挂载的 `discover_backend/.env` 提供。
- **backend**：镜像启动只拉起 uvicorn，不执行数据库迁移——迁移由部署侧手动运行
  `uv run alembic upgrade head`（`DB_HOST` 可能指向远程库，避免容器自动改库）；运行时可写目录
  `storage/` / `logs/` / `workspaces/` 在 dev 直接落在宿主机 `discover_backend/`，在 prod/test 以 bind mount
  落在仓库根目录（`./storage` 等，已加入 `.gitignore`），便于统一查看与备份。
- **frontend**：
  - dev：源码热挂载 + Nuxt dev server，`/api` 反代到 `http://discover_backend:8000`（免 CORS）；
  - prod / test：多阶段构建产物由 nginx 托管，`/api` 反向代理到 backend 服务（SSE 关缓冲）。

### 配置注入

- 后端公共参数（含 `LLM_API_KEY` / `YUANBAO_SEARCH_TOKEN` 空占位）以 YAML 锚点 `x-common-env` 写在三套
  compose 各自文件头部，`services.<svc>.environment` 用 `<<: *common-env` 展开，一处修改三处生效；
  真实密钥不入库：放服务器根目录 `.env`（模板根目录 `.env.example`），compose 自动读取并覆盖默认值。
- `DB_*` 按环境各自声明：prod / test 指向 compose 内 postgres；dev 不内置 postgres，走热挂载 `discover_backend/.env`。
- nginx 反代目标经 `BACKEND_PROXY_PASS` 注入（默认 `http://discover_backend:8000`）。

## 测试环境部署（test）

目标：在服务器上一键拉起 test 全栈（backend + frontend），域名 `research.elecnest.cn` 经宿主机
`nginx-public` 容器网关反代接入。以下步骤除第 0 步（本地提交）外，均在**服务器仓库根目录**执行。
代码就位后不依赖 git，rsync / scp / git pull 均可。

### 前置条件

| 项 | 要求 |
|---|---|
| Docker | 已装 Docker + Compose v2（`docker compose version` 可用） |
| 代码 | 仓库已同步到服务器（见步骤 0） |
| DNS | `research.elecnest.cn` A 记录指向本服务器 |
| 数据库 | test 不内置 postgres，连远程库（默认 `175.178.45.21`，根目录 `.env` 可覆盖 `DB_*`） |
| 密钥 | 根目录 `.env` 配置 `LLM_API_KEY`（必填）、`YUANBAO_SEARCH_TOKEN`（可选，web_search 默认提供方），否则对话 / 搜索工具不可用 |

### 步骤 0 — 提交并同步代码（git 方式需要）

部署资产（`docker-compose.test.yml`、`deploy/nginx/gateway-research.conf` 等）若有未提交改动，
服务器用 `git pull` 拉取前必须先提交推送：

```bash
# 本地
git add -A
git commit -m "deploy: 测试环境部署"
git push
# 服务器
git pull
```

用 rsync / scp 覆盖同步则跳过本步，覆盖后先在服务器校验 compose 配置再启动：
`docker compose -f docker-compose.test.yml config -q`（无输出即合法）。

### 步骤 1 — 配置密钥

```bash
cp .env.example .env
vim .env      # 必填 LLM_API_KEY；按需 YUANBAO_SEARCH_TOKEN（搜索默认 yuanbao，ALIBABA 为备选）
```

> `.env` 模板各变量都有默认值，只覆盖需要改的项。不配置也能启动，但 LLM / 搜索工具不可用。
> 不要用留空值覆盖（会顶掉 compose 默认值），需要默认就整行注释。

### 步骤 2 — 一键启动

```bash
bash deploy/scripts/deploy-test.sh
```

脚本会依次：检查 docker / compose → 构建前后端镜像 → 拉起容器 → 等待前端健康检查
（最长 120s）→ 打印容器状态与访问地址。等价的手动命令：

```bash
docker compose -f docker-compose.test.yml up --build -d
```

### 步骤 3 — 网关反代（首次 / 配置变更时）

前端映射宿主机 `9003`；域名经 `nginx-public` 容器（宿主机 nginx:latest，占用 80/443）反代接入：

```bash
docker cp deploy/nginx/gateway-research.conf nginx-public:/etc/nginx/conf.d/research.elecnest.cn.conf
docker exec nginx-public nginx -t
docker exec nginx-public nginx -s reload
```

> 网关配置改动（`proxy_pass` 目标、SSE 超时等）后重复本步骤即可生效。

### 步骤 4 — 数据库迁移（需要时手动执行）

test 连远程库，容器启动**不自动迁移**（避免误改远程库）。需要更新表结构时：

```bash
docker compose -f docker-compose.test.yml exec discover_backend uv run alembic current       # 当前版本
docker compose -f docker-compose.test.yml exec discover_backend uv run alembic upgrade head  # 升级到最新
```

### 步骤 5 — 验证

- 直连前端：`http://<服务器IP>:9003`
- 域名接入：`http://research.elecnest.cn`
- 后端日志：`docker compose -f docker-compose.test.yml logs -f discover_backend`
- 容器状态：`docker compose -f docker-compose.test.yml ps`

### 重新发布 / 回滚

```bash
# 停止（保留容器）
docker compose -f docker-compose.test.yml down
# 同步新代码后重新构建启动
docker compose -f docker-compose.test.yml up --build -d
# 回滚到上一版本：git pull 到旧提交后重新执行上面的 up --build -d
```

### 常见问题

| 现象 | 排查 |
|---|---|
| 容器启动但对话报错 | 检查根目录 `.env` 的 `LLM_API_KEY`；`docker compose -f docker-compose.test.yml logs -f discover_backend` 看具体错误 |
| 域名打不开 | 检查 DNS；确认步骤 3 网关已配置并 reload；`docker exec nginx-public nginx -t` |
| 构建很慢 / 超时 | 服务器构建目录残留 `node_modules`/`.venv` 会被 `COPY . .` 带入上下文；清理或补 `.dockerignore` |
| DB 连不上 | 确认远程库 `DB_*`（默认 `175.178.45.21`）可达；`.env` 中留空值会覆盖默认值导致失败，删掉该行即可 |

## 本地开发（不经 Docker）

- 后端：`cd discover_backend && uv sync && uv run uvicorn app.application:create_app --factory --reload`
  （依赖 PostgreSQL，连接配置见 `discover_backend/.env`）。
- 前端：`cd discover_frontend && pnpm install && pnpm dev`（`/api` 默认代理到 `http://127.0.0.1:8000`）。

> 各子项目详细文档：`discover_backend/README.md`、`discover_frontend/README.md`。
