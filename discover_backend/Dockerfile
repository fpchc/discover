FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm AS base

# 1. 从官方轻量镜像直接复制 uv 二进制文件，避免 pip 安装开销
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 2. 全局环境变量配置：默认使用阿里云 PyPI 镜像，禁止自动下载 Python 解释器
# 腾讯云地址
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

# 3. 依赖安装层：显式指定阿里源，开启缓存挂载与并发限制（4 线程）
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --default-index https://mirrors.aliyun.com/pypi/simple/ \
    --concurrent-downloads 4 \
    --frozen \
    --no-dev \
    --no-install-project

# 4. 源码安装层
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --default-index https://mirrors.aliyun.com/pypi/simple/ \
    --concurrent-downloads 4 \
    --frozen \
    --no-dev

# 运行时目录
RUN mkdir -p storage workspaces

EXPOSE 9101

# 生产启动命令
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9101"]
