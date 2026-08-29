# discover_frontend

ChatGPT 风格单页对话应用，消费 `discover_backend` 多智能体平台（单用户、无鉴权演示）。
仅消费已有 API（`POST /api/v1/chat-messages`，SSE 流式），不新增后端接口；会话列表 / 消息历史由后端接口持有，前端不落本地。

## 技术栈

React 19 · TypeScript(strict) · Vite（纯客户端 SPA，静态产物 `dist/`）· Tailwind CSS 4 · shadcn/ui（Radix）· Zustand ·
motion · Axios · react-markdown + highlight.js + DOMPurify · sonner · lucide-react · **Biome**（lint+format 单一规则源）· Vitest + Testing Library

## 快速开始

- 环境：Node `>= 20.19`，pnpm `>= 9`（`corepack enable`）
- 安装：`pnpm install`
- 本地开发：`pnpm dev`（`/api` 代理到 `VITE_PROXY_TARGET`，默认 `http://127.0.0.1:8000`）

## 三环境架构

环境文件统一收容于 `env/`（vite `envDir` 原生注入 `import.meta.env`），本地覆盖用 `env/.env.development.local`（gitignore）：

| 环境 | 启动方式 | 说明 |
|---|---|---|
| **dev** | `pnpm dev` / `docker compose up --build` | vite dev 热更新，`/api` 走 `server.proxy` 代理（免 CORS） |
| **test** | `pnpm build:test` 或 `docker compose -f docker-compose.test.yml up --build -d` | test 模式构建 + nginx 反代（9003） |
| **prod** | `pnpm build` && `pnpm preview` 或 `docker compose -f docker-compose.prod.yml up --build -d` | vite build 静态产物 + nginx 反代（8080） |

> prod / test 的根级 compose 为全栈编排（postgres + 后端 + 前端）；`docker compose up frontend` 也会连带启动其依赖（后端）。dev 编排不内置 postgres。
> 反代目标经 compose 环境变量 `BACKEND_PROXY_PASS` 注入（默认 `http://discover_backend:8000`，compose 服务名）。

## 质量门禁（提交前，见 CLAUDE.md 第 13 节）

```bash
pnpm lint        # Biome：lint + format 单一规则源
pnpm typecheck   # tsc --noEmit（TS strict）
pnpm test:run    # vitest（jsdom + Testing Library）
pnpm build:test  # tsc --noEmit + vite build --mode test
```

CI（`.github/workflows/ci.yml`）将以上四项**并行**执行。

## Docker

前端自带构建文件（`Dockerfile` / `nginx.conf` / `security-headers.conf` 位于本目录根），
根级 compose 以 `context: ./discover_frontend` 引用，与后端 / postgres 组成全栈编排：

```
discover_frontend/
├── Dockerfile              多阶段：base → deps → dev → build → runtime(nginx)，产物 dist/
├── nginx.conf              SSE 反代(proxy_buffering off) + /assets/ hash 长缓存（envsubst 模板）
├── security-headers.conf   CSP / X-Frame-Options 等安全头 snippet
└── .dockerignore
docker-compose.yml          dev 编排（后端热重载 + 前端热更新；不内置 postgres）
docker-compose.prod.yml     prod 全栈（nginx 反代，8080）
docker-compose.test.yml     test 全栈（nginx 反代，9003）
```

```bash
# dev（全栈热更新：前端 5173 / 后端 8000）
docker compose up --build
# prod（8080）
docker compose -f docker-compose.prod.yml up --build -d
# test（9003）
docker compose -f docker-compose.test.yml up --build -d
```

> 后端镜像与全栈编排细节见仓库根 `README.md`。

## 目录速查

- 架构快照 / 模块映射：`.ai/ARCHITECTURE.md`、`.ai/MODULE_MAP.md`（结构变化后同步更新）
- 架构规范（分层 / 依赖方向 / 边界）：`.claude/commands/architecture.md`
- 性能与状态粒度红线（SSE 高频路径）：`.claude/commands/performance.md`
- 需求 / API 契约：`.claude/feature/REQUIREMENTS.md`、`.claude/feature/API.md`
- 全局红线约束：`CLAUDE.md`

## 已知限制

- **单 chunk ~786KB（gzip ~251KB）**：react-dom + motion + radix 体积合理；`chunkSizeWarningLimit` 已调至 800。
  若后续继续增大，可考虑 `build.rolldownOptions.output.codeSplitting` 拆 vendor 或按需懒加载。
- **react-markdown 默认不渲染原始 HTML**：模型输出中的原生 HTML 会被跳过（安全收敛，见 CLAUDE.md 第 6 节）。
- `pnpm-workspace.yaml` 非 Monorepo 声明，是 pnpm 11 的设置文件（`allowBuilds.esbuild`），删除会导致依赖安装报 `ERR_PNPM_IGNORED_BUILDS`。
