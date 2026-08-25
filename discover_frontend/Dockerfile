# ===== discover_frontend 多阶段构建 =====
# 构建上下文为当前目录（discover_frontend/），根级 compose 指定 context: ./discover_frontend。
# 阶段一 base：运行时 + 包管理器
FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /app

# 阶段二 dev：热更新开发服务（docker compose 默认目标）
FROM base AS dev
# pnpm-workspace.yaml 为 pnpm 11 设置文件（allowBuilds.esbuild），install 必须包含它
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
EXPOSE 5173
CMD ["pnpm", "dev", "--host", "0.0.0.0"]

# 阶段三 build：安装依赖并构建静态产物
FROM base AS build
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# 构建期环境：VITE_* 在构建时烘焙进产物；ENV 优先级高于 env/ 下的 .env 文件
ARG VITE_APP_ENV=production
ARG VITE_API_BASE_URL=/api/v1
# 流式请求整体超时（ms）：长思考/工具调用流超过 5 分钟会误判超时，默认放宽到 15 分钟
ARG VITE_SSE_TIMEOUT_MS=900000
ENV VITE_APP_ENV=$VITE_APP_ENV \
    VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_SSE_TIMEOUT_MS=$VITE_SSE_TIMEOUT_MS
RUN pnpm build

# 阶段四 runtime：nginx 静态服务 + 后端反代（SSE 优化）
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
