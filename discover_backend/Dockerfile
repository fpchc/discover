# ===== discover_backend（多智能体承载平台）镜像 =====
# 构建上下文为当前目录（discover_backend/），根级 compose 指定 context: ./discover_backend。
# 依赖管理走 uv（pyproject.toml + uv.lock 锁定），应用入口见 pyproject.toml。
#
# 国内加速：基础镜像与 Python 依赖全部走阿里云源
#   - 基础镜像：Docker Hub 官方镜像 → registry.cn-hangzhou.aliyuncs.com/library/（阿里云容器镜像服务）
#   - uv 本体：阿里云 PyPI 镜像 pip 安装（uv 官方 Docker 镜像仅发布在 ghcr.io，国内拉取极慢，故弃用）
#   - Python 依赖：pypi.org → mirrors.aliyun.com/pypi/simple（阿里云 PyPI 镜像，uv sync 走此源）
FROM registry.cn-hangzhou.aliyuncs.com/library/python:3.12-slim-bookworm AS base
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/
WORKDIR /app

# 安装 uv（uv 二进制分发到 PyPI，走阿里云镜像拉取）
RUN pip install uv

# 依赖层：仅 pyproject.toml / uv.lock 变更时重建（利用 Docker 层缓存）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 源码层：安装项目自身（含 console 入口脚本）
COPY . .
RUN uv sync --frozen --no-dev

# 运行时可写目录：storage / logs / workspaces 以卷挂载持久化，镜像内预留空目录
RUN mkdir -p storage logs/tools workspaces

EXPOSE 8000
# 启动：仅拉起 uvicorn（host/port 配置驱动；入口见 app/main.py）。
# --no-dev：镜像只装了运行依赖（uv sync --no-dev），防止 uv run 启动时再把 dev 组装一遍。
# 数据库迁移不在容器内执行——DB_HOST 可能指向远程库，迁移由部署侧手动跑 alembic upgrade head。
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# dev 目标：源码热挂载（compose 里绑 ./discover_backend:/app）+ --reload
FROM base AS dev
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
