#!/usr/bin/env bash
# ===== 测试环境一键启动（在服务器仓库根目录执行；不涉及 git 操作）=====
# 前置：
#   1) 服务器已装 Docker + Docker Compose v2，代码已就位（rsync / scp / 手动覆盖均可，无需 git pull）；
#   2) 根目录 .env 已按 .env.example 填写（LLM_API_KEY / ALIBABA_SEARCH_TOKEN / DB_*）；
#      未填写也能启动，但 LLM / 搜索工具不可用，DB 走 compose 内置默认值（远程库 175.178.45.21）。
#   3) 域名 research.elecnest.cn 的 DNS 已指向本机，网关配置见 deploy/nginx/gateway-research.conf。
#   4) test 环境不内置 postgres，连远程库；数据库迁移不自动执行（避免误改远程库），
#      需要时按脚本末尾提示手动运行。
#
# 用法：  bash deploy/scripts/deploy-test.sh
set -euo pipefail

COMPOSE_FILE="docker-compose.test.yml"
BACKEND_SERVICE="discover_backend"
FRONTEND_SERVICE="discover_frontend"

say()  { printf '\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

# ---- 0/5 前置检查 ----
if ! command -v docker >/dev/null 2>&1; then
  echo "错误：未找到 docker，请先安装 Docker 再执行本脚本。" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "错误：docker compose 不可用（需要 Docker Compose v2 的 docker compose 命令）。" >&2
  exit 1
fi
if [ ! -f "${COMPOSE_FILE}" ]; then
  echo "错误：未找到 ${COMPOSE_FILE}，请在仓库根目录执行本脚本。" >&2
  exit 1
fi

# ---- 1/5 .env 检查（缺失不阻断，给出提示）----
if [ -f .env ]; then
  say ".env 已存在"
else
  warn "根目录未找到 .env，将以 compose 内置默认值启动："
  warn "  · LLM_API_KEY 为空 → 对话不可用"
  warn "  · ALIBABA_SEARCH_TOKEN 为空 → 搜索工具不可用"
  warn "  · DB_* 走默认远程库 175.178.45.21"
  warn "建议先配置：cp .env.example .env 后填写真实密钥，再执行本脚本。"
fi

# ---- 2/5 构建并启动 ----
say "构建并启动测试环境（${COMPOSE_FILE}）"
docker compose -f "${COMPOSE_FILE}" up --build -d

# ---- 3/5 等待前端就绪（frontend 镜像内置 HEALTHCHECK）----
say "等待前端就绪（最长 120s）"
frontend_ready=false
for _ in $(seq 1 60); do
  cid="$(docker compose -f "${COMPOSE_FILE}" ps -q "${FRONTEND_SERVICE}" 2>/dev/null | head -n 1 || true)"
  if [ -z "${cid}" ]; then
    sleep 2
    continue
  fi
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${cid}" 2>/dev/null || echo none)"
  case "${status}" in
    healthy)
      frontend_ready=true
      break
      ;;
    unhealthy)
      warn "前端健康检查异常（${FRONTEND_SERVICE}），查看日志："
      warn "  docker compose -f ${COMPOSE_FILE} logs -f ${FRONTEND_SERVICE}"
      break
      ;;
    *) sleep 2 ;;
  esac
done
if [ "${frontend_ready}" != "true" ]; then
  warn "前端未在 120s 内就绪，可继续观察：docker compose -f ${COMPOSE_FILE} logs -f"
fi

# ---- 4/5 迁移提醒（不自动执行，避免误改远程库）----
say "数据库迁移（默认不自动执行）"
echo "  当前版本：  docker compose -f ${COMPOSE_FILE} exec ${BACKEND_SERVICE} uv run alembic current"
echo "  升级到最新： docker compose -f ${COMPOSE_FILE} exec ${BACKEND_SERVICE} uv run alembic upgrade head"

# ---- 5/5 完成 ----
say "容器状态："
docker compose -f "${COMPOSE_FILE}" ps
echo ""
echo "  访问方式："
echo "    http://<服务器IP>:9003          # 直连前端"
echo "    http://research.elecnest.cn     # 经宿主机网关（需已配置 deploy/nginx/gateway-research.conf）"
