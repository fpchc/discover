# 多智能体承载平台

多智能体承载平台：提供运行时（图循环）、工具接入（MCP + 脚本）、会话与隔离、
流式输出、审批、产物管理。平台不含业务逻辑——具体业务属于 `agents/` 下的智能体包。

> 对话接口对齐 chat-messages 契约（`POST /chat-messages`，会话自动创建）。
> 完整架构规划见 `.claude/commands/*.md`。

## 目录结构

```text
src/platform_engine/  平台代码（不含业务）
agents/              智能体包（数据，可挂载卷）
config/              平台配置（非密钥，.example 样例）
alembic/             DB 迁移
tests/               测试
```

> 包根名取 `platform_engine`（非 `platform`）：`platform` 与 Python 标准库模块同名，会导致导入被 stdlib 截获。
> 本目录自带 `Dockerfile` / `.dockerignore`，根级 compose 以 `context: ./discover_backend` 引用，见仓库根 `README.md`。

## 开发环境

- 安装依赖：`uv sync`
- 代码校验：`uv run ruff check . && uv run ruff format --check . && uv run mypy src/platform_engine`
- 测试：`uv run pytest`
- 开发服务器：`uv run uvicorn platform_engine.api.app:create_app --factory --reload`

### Docker（统一在仓库根编排）

后端镜像定义在本目录根 `Dockerfile`（uv 安装依赖 → Alembic 迁移 → uvicorn 启动），
与前端 / postgres 通过根级 `docker-compose*.yml` 一键拉起（见仓库根 `README.md`）：

```bash
# dev：postgres + 后端热重载 + 前端热更新
docker compose up --build
# prod：仅后端（+ postgres）
docker compose -f docker-compose.prod.yml up --build -d backend
```

容器内通过环境变量注入 DB / LLM 等配置（`DB_HOST` 指向 compose 的 `postgres` 服务），
密钥走宿主机 `discover_backend/.env`（compose `env_file`，可缺省）。

## 对话接口（chat-messages）

`POST /api/v1/chat-messages`：`conversation_id` 空串自动创建会话，续聊带上即复用
会话状态；`conversation_id` 经响应体与响应头 `X-Conversation-Id` 返回。
`response_mode=streaming` 走 SSE（`event` 判别帧：`message` / `message_end` /
`ping` / `error`），`blocking` 返回 JSON。`files` 字段接受但暂不处理。

```bash
# blocking
curl -X POST http://127.0.0.1:8000/api/v1/chat-messages \
  -H 'Content-Type: application/json' \
  -d '{"query":"帮我找客户","response_mode":"blocking","conversation_id":""}'
```

```bash
# streaming（SSE，无 [DONE]，以 message_end 收尾）
curl -N -X POST http://127.0.0.1:8000/api/v1/chat-messages \
  -H 'Content-Type: application/json' \
  -d '{"query":"帮我找客户","response_mode":"streaming","conversation_id":""}'
```

其他接口：`GET /api/v1/sessions/{id}/artifacts/{aid}`（产物下载）。

## 规范

- 全局硬约束：`CLAUDE.md`
- 单项职责规范：`.claude/commands/*.md`
- 架构记忆：`.ai/*.md`
