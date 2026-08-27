#!/usr/bin/env bash
# ===== 测试环境一键部署（在服务器仓库根目录执行）=====
# 前置：
#   1) 服务器已装 Docker + Docker Compose，仓库已 clone 到本目录；
#   2) 密钥（LLM_API_KEY / ALIBABA_SEARCH_TOKEN / DB_* 等）通过根目录 .env 注入
#      （compose 自动读取同目录 .env，覆盖 x-common-env 默认值）；
#   3) 域名 research.elecnest.cn 的 DNS 已指向本机，网关配置见
#      deploy/nginx/gateway-research.conf（80 反代到 8081）。
#
# 用法：  bash deploy/scripts/deploy-test.sh
set -euo pipefail

COMPOSE_FILE="docker-compose.test.yml"

echo "==> 1/4 拉取最新代码"
git pull --ff-only

echo "==> 2/4 构建并启动测试环境 (${COMPOSE_FILE})"
docker compose -f "${COMPOSE_FILE}" up --build -d

echo "==> 3/4 容器状态"
docker compose -f "${COMPOSE_FILE}" ps

echo "==> 4/4 完成。访问方式："
echo "    http://<服务器IP>:8081          # 直连前端"
echo "    http://research.elecnest.cn     # 经宿主机网关（需已配置 deploy/nginx/gateway-research.conf）"
