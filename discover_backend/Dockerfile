FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm AS base
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
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
RUN mkdir -p storage workspaces

EXPOSE 8000
# 启动：仅拉起 uvicorn（host/port 配置驱动；入口见 app/main.py）。
# --no-dev：镜像只装了运行依赖（uv sync --no-dev），防止 uv run 启动时再把 dev 组装一遍。
# 数据库迁移不在容器内执行——DB_HOST 可能指向远程库，迁移由部署侧手动跑 alembic upgrade head。
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# dev 目标：源码热挂载（compose 里绑 ./discover_backend:/app）+ --reload
FROM base AS dev
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
