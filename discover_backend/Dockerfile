# syntax=docker/dockerfile:1

# 国内稳定镜像：DaoCloud 的 Docker Hub 镜像加速，避免直连 Docker Hub 超时
FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm AS base

# 1. 通过国内 PyPI 镜像安装 uv。
#    原方案 COPY --from=ghcr.io/astral-sh/uv 会请求 ghcr.io，国内网络常报
#    "failed to fetch anonymous token ... EOF"，这里改为从阿里云 PyPI 安装，
#    同时把 uv 版本锁定为与 uv.lock 一致的 0.12.3，保证构建可复现。
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG UV_VERSION=0.12.3
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

# 2. 全局环境变量配置（将并发数、源、虚拟环境 PATH 全部放入 ENV 统一管理）
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_CONCURRENT_DOWNLOADS=4 \
    UV_DEFAULT_INDEX=${PIP_INDEX_URL} \
    UV_INDEX_URL=${PIP_INDEX_URL} \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 3. 依赖安装层
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --frozen \
    --no-dev \
    --no-install-project

# 4. 源码安装层
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --frozen \
    --no-dev

# 运行时目录
RUN mkdir -p storage workspaces

EXPOSE 9101

# 生产启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9101", "--timeout-graceful-shutdown", "5"]
