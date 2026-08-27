# discover_frontend

ChatGPT 风格单页对话应用，消费 `discover_backend` 多智能体平台（单用户、无鉴权演示）。
仅消费已有 API（`POST /api/v1/chat-messages`，SSE 流式），不新增后端接口；会话历史由后端持有，前端仅本地持久化会话元数据。

## 技术栈

Vue 3.5 · TypeScript(strict) · Nuxt 4（SPA，`ssr:false`）· Element Plus · Pinia · Axios · markdown-it + highlight.js + DOMPurify · **Biome**（lint+format 单一规则源）· Vitest

## 快速开始

- 环境：Node `>= 20.19`，pnpm `>= 9`（`corepack enable`）
- 安装：`pnpm install`
- 本地开发：`pnpm dev`（`/api` 代理到 `VITE_PROXY_TARGET`，默认 `http://127.0.0.1:8000`）

## 三环境架构

环境文件统一收容于 `env/`（经 `--dotenv ./env/.env.{development,test,production}` 加载，注入 process.env 流入 `import.meta.env`），本地覆盖用 `env/.env.development.local`（gitignore）：

| 环境 | 启动方式 | 说明 |
|---|---|---|
| **dev** | `pnpm dev` / `docker compose up --build` | nuxt dev 热更新，`/api` 走 nitro.devProxy 代理（免 CORS） |
| **test** | `pnpm dev:test` 或 `docker compose -f docker-compose.test.yml up --build -d` | test 模式构建 + nginx 反代（8081） |
| **prod** | `pnpm build` && `pnpm preview` 或 `docker compose -f docker-compose.prod.yml up --build -d` | nuxt generate 静态产物 + nginx 反代（8080） |

> prod / test 的根级 compose 为全栈编排（postgres + 后端 + 前端）；`docker compose up frontend` 也会连带启动其依赖（后端）。dev 编排不内置 postgres。
> 反代目标经 compose 环境变量 `BACKEND_PROXY_PASS` 注入（默认 `http://discover_backend:8000`，compose 服务名）。

## 质量门禁（提交前，见 CLAUDE.md 第 12 节）

```bash
pnpm lint        # Biome：lint + format 单一规则源
pnpm typecheck   # nuxt typecheck（vue-tsc，基于 .nuxt/tsconfig.json）
pnpm test:run    # vitest（happy-dom）
pnpm build:test  # nuxt typecheck + nuxt generate --dotenv ./env/.env.test
```

CI（`.github/workflows/ci.yml`）将以上四项**并行**执行。

## Docker

前端自带构建文件（`Dockerfile` / `nginx.conf` / `security-headers.conf` 位于本目录根），
根级 compose 以 `context: ./discover_frontend` 引用，与后端 / postgres 组成全栈编排：

```
discover_frontend/
├── Dockerfile              多阶段：base → dev → build → runtime(nginx)
├── nginx.conf              SSE 反代(proxy_buffering off) + hash 长缓存（envsubst 模板）
├── security-headers.conf   CSP / X-Frame-Options 等安全头 snippet
└── .dockerignore
docker-compose.yml          dev 编排（后端热重载 + 前端热更新；不内置 postgres）
docker-compose.prod.yml     prod 全栈（nginx 反代，8080）
docker-compose.test.yml     test 全栈（nginx 反代，8081）
```

```bash
# dev（全栈热更新：前端 3000 / 后端 8000）
docker compose up --build
# prod（8080）
docker compose -f docker-compose.prod.yml up --build -d
# test（8081）
docker compose -f docker-compose.test.yml up --build -d
```

> 后端镜像与全栈编排细节见仓库根 `README.md`。

## 目录速查

- 架构快照 / 模块映射：`.ai/ARCHITECTURE.md`、`.ai/MODULE_MAP.md`（结构变化后同步更新）
- 架构规范（分层 / 依赖方向 / 边界）：`.claude/commands/architecture.md`
- 全局红线约束：`CLAUDE.md`

## 已知限制

- **Biome × Vue**：Biome 暂不识别 `<script setup>` 模板绑定，`biome.json` 对 `.vue` 关闭
  `noUnusedVariables` / `noUnusedImports`（避免误删模板引用变量）；TS 文件仍启用。
- Element Plus 经 `@element-plus/nuxt` 按需引入；其 Vite `optimizeDeps.include` 需 `dayjs` / `lodash-unified`
  可解析，故列为 devDependencies 直装。
- `pnpm-workspace.yaml` 非 Monorepo 声明，是 pnpm 11 的设置文件（`allowBuilds.esbuild`），删除会导致依赖安装报 `ERR_PNPM_IGNORED_BUILDS`。
