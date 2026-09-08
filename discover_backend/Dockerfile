FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm AS base

# 1. 从官方轻量镜像直接复制 uv 二进制文件
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 2. 全局环境变量配置（将并发数、源、虚拟环境 PATH 全部放入 ENV 统一管理）
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_CONCURRENT_DOWNLOADS=4 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ \
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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9101"]
