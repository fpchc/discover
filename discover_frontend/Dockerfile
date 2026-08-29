# syntax=docker/dockerfile:1
# ===== discover_frontend 多阶段构建 =====
# 构建上下文为当前目录（discover_frontend/），根级 compose 指定 context: ./discover_frontend。
# 需 BuildKit（Docker ≥ 23 默认开启）：--mount=type=cache 将 pnpm 全局 store 与 corepack
# 缓存持久化到构建缓存，lockfile 未变的重复构建不重新联网下载依赖，install 提速到秒级。
# 阶段一 base：运行时 + 包管理器
FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /app

# 阶段二 deps：一次性安装依赖（dev / build 共用，原两处重复 install 合并为一处）
FROM base AS deps
# 可选 npm 镜像源：国内构建可传 --build-arg PNPM_REGISTRY=https://registry.npmmirror.com
# lockfile v9 的 tarball 由 registry 配置解析，改镜像即改下载源，无需改 lockfile
ARG PNPM_REGISTRY=https://registry.npmjs.org/
# pnpm-workspace.yaml 为 pnpm 11 设置文件（allowBuilds.esbuild），install 必须包含它
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    --mount=type=cache,id=corepack,target=/root/.cache/node/corepack \
    pnpm install --frozen-lockfile --prefer-offline --registry="$PNPM_REGISTRY"

# 阶段三 dev：热更新开发服务（docker compose 默认目标）
FROM deps AS dev
EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0"]

# 阶段四 build：构建静态产物（node_modules 继承自 deps 镜像层，源码变更不重装依赖）
FROM deps AS build
COPY . .
# 构建期环境：VITE_* 在构建时烘焙进产物；ENV（process.env）优先级高于 --dotenv 加载的 env/ 文件
ARG VITE_APP_ENV=production
ARG VITE_API_BASE_URL=/api/v1
# 流式请求整体超时（ms）：长思考/工具调用流超过 5 分钟会误判超时，默认放宽到 15 分钟
ARG VITE_SSE_TIMEOUT_MS=900000
ENV VITE_APP_ENV=$VITE_APP_ENV \
    VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_SSE_TIMEOUT_MS=$VITE_SSE_TIMEOUT_MS
# pnpm build = tsc --noEmit + vite build（SPA 静态产物输出到 dist/）
RUN pnpm build

# 阶段五 runtime：nginx 静态服务 + 后端反代（SSE 优化）
FROM nginx:1.27-alpine AS runtime
# 官方 nginx 镜像启动时对 /etc/nginx/templates/*.template 执行 envsubst，
# 将 ${BACKEND_PROXY_PASS} 替换为后端地址
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
