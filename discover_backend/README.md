# discover_backend — 多智能体承载平台后端

FastAPI + LangGraph 多智能体承载平台后端：统一认证、会话/消息落库、文件存储、Agent
技能包装配、本地自建 MCP 服务（腾讯联网搜索 / 东方财富资讯）。

---

## 部署（生产环境）

正式环境**唯一启动方式是 Docker Compose**，部署文件全部收拢在 `deploy/`。

### 交付物

| 交付物 | 说明 |
|---|---|
| 镜像 `discover-backend:<版本号>` | **一个镜像跑三个角色**：backend API、tencent_mcp、eastmoney_mcp，仅启动命令与环境变量不同；**按版本号打标签**（如 `1.0.0`），便于回滚 |
| `deploy/` 目录 | 生产编排 + 数据库 SQL 脚本 |

镜像构建交付（版本号随发版递增，如 `1.0.0` → `1.1.0`）：

```bash
docker build -t discover-backend:1.0.0 .
# 推送私有仓库，或离线交付
docker save discover-backend:1.0.0 | gzip > discover-backend-1.0.0.tar.gz
# 目标服务器导入
gunzip -c discover-backend-1.0.0.tar.gz | docker load
```

### deploy/ 目录结构

```
deploy/
├── docker-compose.yml           # 生产编排（唯一启动方式）
└── db/
    ├── init.sql                 # 首次初始化（开发侧提供，全新空库执行一次）
    └── upgrades/<版本>.sql      # 每次版本增量更新（开发侧提供，按序执行）
```

### 前置依赖

- **PostgreSQL 16+**：外部提供，连接串经 `deploy/.env` 注入。
- **Redis**：外部提供，**认证会话层硬依赖**（登录会话/过期/撤销/续期以 Redis 为准），

### 环境变量

首次部署在 `deploy/` 下准备 `.env`：

```bash
cp .env.example deploy/.env   # 以 .env.example 为字段清单，值替换为正式环境真实值
```

**必须提供**：

| 变量 | 用途 |
|---|---|
| `DISCOVER_VERSION` | 镜像版本号（如 `1.0.0`），决定跑哪个版本；**回滚时改回旧版本号** |
| `DB_USERNAME` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT` / `DB_DATABASE` | PostgreSQL 连接 |
| `REDIS_URL` | Redis 连接串（如 `redis://<host>:6379/0`） |


### 数据库

> 正式环境**禁止**在数据库上运行任何迁移类操作（如 alembic upgrade）；所有结构变更
> 一律由开发侧产出 SQL 脚本，由 DBA 执行。

**首次初始化（一次性）**：确认数据库存在后，执行开发侧提供的全量 `deploy/db/init.sql`
（建表 + 系统账号，幂等，只对全新空库执行一次）：

```bash
psql "postgresql://<user>:<password>@<db-host>:5432/agent_platform" \
  -v ON_ERROR_STOP=1 -f deploy/db/init.sql
```

**版本更新（每个版本一次）**：每次发版，开发侧随新镜像提供增量 SQL
`deploy/db/upgrades/<版本>.sql`。执行顺序：

1. 备份：`pg_dump "postgresql://<user>:<password>@<db-host>:5432/agent_platform" -F c -f agent_platform_$(date +%Y%m%d_%H%M%S).dump`
2. 低峰期按版本顺序执行增量脚本（`-v ON_ERROR_STOP=1 -f deploy/db/upgrades/<版本>.sql`）。
3. 校验版本：`SELECT version_num FROM alembic_version;` 应与发版说明一致（增量 SQL 由
   Alembic 离线生成时自带 `alembic_version` 维护）。
4. 确认无报错后再升级服务镜像（**先库后服务**）。

### 启动（唯一方式）

镜像就绪、`deploy/.env` 配置好后，在 `deploy/` 目录：

```bash
cd deploy
docker compose up -d    # 启动三个角色（按 .env 的 DISCOVER_VERSION 拉取对应版本镜像）
docker compose ps       # 查看状态
docker compose logs -f backend
docker compose down     # 停止（deploy/storage、logs、workspaces 与外部 DB 数据保留）
```

切换版本：修改 `deploy/.env` 的 `DISCOVER_VERSION` 后重新 `docker compose up -d`，
镜像标签变化会自动重建容器。

三个角色与端口：

| 角色 | 容器名 | 对外端口 |
|---|---|---|
| backend API | `discover_backend` | 9101 |
| tencent_mcp | `tencent_mcp` | 9111 |
| eastmoney_mcp | `eastmoney_mcp` | 9112 |

后端经 compose 网络以 `http://tencent_mcp:9111/mcp` / `http://eastmoney_mcp:9112/mcp`
访问两个 MCP 角色（编排内联覆盖）。

### 健康检查与验证

| 目标 | 命令 | 期望 |
|---|---|---|
| backend | `curl -s http://<host>:9101/docs` | HTTP 200 |
| tencent_mcp | `curl -s http://<host>:9111/health` | HTTP 200 |
| eastmoney_mcp | `curl -s http://<host>:9112/health` | HTTP 200 |
| Redis | `redis-cli -h <redis-host> ping` | `PONG` |
| PostgreSQL | `pg_isready -h <db-host> -p 5432 -U <user>` | `accepting connections` |

### 升级流程（新版本）

1. 取得新版本镜像（如 `discover-backend:1.1.0`）：重新构建 / `docker pull` / `docker load`。
2. **先更新数据库**：备份后执行增量 SQL（见「数据库 → 版本更新」）。
3. 修改 `deploy/.env` 的 `DISCOVER_VERSION=1.1.0`。
4. 切换版本：`cd deploy && docker compose up -d`（镜像标签变化自动重建容器）。
5. 验证：`docker compose ps` 三容器 Running，`curl -s http://<host>:9101/docs` 返回 200。
6. **回滚**：把 `deploy/.env` 的 `DISCOVER_VERSION` 改回旧版本号（如 `1.0.0`），再次
   `docker compose up -d`。旧版本镜像需保留在宿主机（勿执行 `docker image prune`），
   以便随时回滚；数据库按需用备份恢复。
