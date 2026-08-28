# deploy/ — 部署物统一管理

> 前后端 Dockerfile 一律不动。前端 `nginx.conf` / `security-headers.conf` / `env/` 因被
> Dockerfile 构建期 COPY 或 `pnpm build --dotenv` 引用，必须留在 `discover_frontend/`；
> 后端 `config/*.yaml` 是容器内运行时路径 `/app/config/...`，也留在 `discover_backend/`。
> 本目录集中存放 compose 之外的部署配置、网关反代、部署脚本与说明，做到部署物只看根目录。

## 三套环境

| 环境 | compose 文件 | 前端端口 | 域名接入 |
|---|---|---|---|
| dev  | `docker-compose.yml` | 前端 3000 / 后端 8000 | — |
| prod | `docker-compose.prod.yml` | 8080 | 待确认 |
| test | `docker-compose.test.yml` | 9003 | `research.elecnest.cn`（经宿主机网关反代） |

## 目录

```text
deploy/
├── README.md                      # 本文件：部署物索引
├── nginx/
│   └── gateway-research.conf      # 宿主机网关：research.elecnest.cn(80) → 127.0.0.1:9003（HTTP）
└── scripts/
    └── deploy-test.sh             # 测试环境一键部署（服务器上执行）
```

## 配置文件归属（为什么这些文件不在本目录）

| 配置 | 所在位置 | 原因 |
|---|---|---|
| `nginx.conf` | `discover_frontend/` | Dockerfile runtime 阶段 `COPY` 打进镜像 |
| `security-headers.conf` | `discover_frontend/` | Dockerfile runtime 阶段 `COPY` |
| `env/.env.*` | `discover_frontend/env/` | `pnpm build --dotenv ./env/...` 在容器内引用 |
| `config/mcp-servers.yaml`、`config/llm-providers.yaml` | `discover_backend/` | 容器内 `/app/config/...` 运行时路径 |

## 测试环境部署步骤

> 完整 runbook（步骤 0 代码同步 → 密钥 → 一键启动 → 网关 → 迁移 → 验证 → 回滚 → 常见问题）
> 见仓库根目录 `README.md` 的「测试环境部署（test）」一节，本目录只列精简版。

```bash
# 0. 提交并推送未提交的部署资产（若服务器用 git pull 拉取；rsync/scp 则跳过并先校验）
git add -A && git commit -m "deploy: 测试环境部署" && git push
docker compose -f docker-compose.test.yml config -q   # 服务器上校验（无输出即合法）
# 1. DNS：research.elecnest.cn 指向部署服务器
# 2. 服务器上，仓库根目录，先配密钥（模板见根目录 .env.example；LLM_API_KEY 必填）
cp .env.example .env && $EDITOR .env
# 3. 一键启动（脚本不含 git 操作；test 不内置 postgres，连远程库，迁移需手动执行）
bash deploy/scripts/deploy-test.sh
# 4. 网关：把 deploy/nginx/gateway-research.conf 挂进宿主机 nginx-public 容器的 conf.d/ 并 reload
docker cp deploy/nginx/gateway-research.conf nginx-public:/etc/nginx/conf.d/research.elecnest.cn.conf
docker exec nginx-public nginx -t && docker exec nginx-public nginx -s reload
#    reload 后 http://research.elecnest.cn 生效（HTTPS 后续再配，需证书）
```

## 密钥注入

真实密钥不入库。`x-common-env` 全部是 `${VAR:-默认值}`，服务器根目录放 `.env`
（compose 自动读取），用 `LLM_API_KEY=`、`YUANBAO_SEARCH_TOKEN=`（web_search 默认走
yuanbao；`ALIBABA_SEARCH_TOKEN=` 为 failover 备选）、`DB_*` 覆盖默认值。
模板：根目录 `.env.example`（已加入 `.gitignore` 白名单，可提交）。
