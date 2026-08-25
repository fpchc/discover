# 多智能体承载平台

多智能体承载平台：提供运行时（图循环）、工具接入（MCP + 脚本）、会话与隔离、
流式输出、审批、产物管理。平台不含业务逻辑——具体业务属于 `agents/` 下的智能体包。

> 对话接口契约（`POST /chat-messages`，会话自动创建）。
> 完整架构规划见 `.claude/commands/*.md`。

## 目录结构

```text
app/  平台代码（不含业务）
agents/              智能体包（数据，可挂载卷）
config/              平台配置（非密钥，.example 样例）
frontend/            Chat UI
docker/              镜像与编排定义
tests/               测试
```

> 包根名为 `app`（仓库根单层包，无 src/ 包裹；`api/` 仅暴露路由，如 Java controller）。

## 开发环境

- 安装依赖：`uv sync`
- 代码校验：`uv run ruff check . && uv run ruff format --check . && uv run mypy app`
- 测试：`uv run pytest`
- 开发服务器：`uv run uvicorn app.application:create_app --factory --reload`

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
