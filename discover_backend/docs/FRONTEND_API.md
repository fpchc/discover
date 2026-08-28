# 平台前端 API 文档

> 给前端实现的完整接口契约。所有接口前缀 `/api/v1`；域名为`http://research.elecnest.cn`,除特殊说明外请求/响应均为
> JSON。聊天用 `POST /chat-messages`（默认 SSE 流式），其余为 REST 检索。
>
> 本文件基于当前后端实现（OpenAPI 快照 + 代码）整理，是前端对接的唯一契约。

## 目录

- [0. 通用约定](#0-通用约定)
- [1. 对话 `POST /chat-messages`（核心）](#1-对话-post-chat-messages核心)
  - [1.1 请求体](#11-请求体)
  - [1.2 agent_id 语义（显式选择助手）](#12-agent_id-语义显式选择助手)
  - [1.3 响应头](#13-响应头)
  - [1.4 blocking 模式响应（200 JSON）](#14-blocking-模式响应200-json)
  - [1.5 streaming 模式响应（SSE 流结构）](#15-streaming-模式响应sse-流结构)
- [2. 文件接口](#2-文件接口)
- [3. 会话接口](#3-会话接口)
- [4. 助手目录](#4-助手目录)
- [5. 错误与状态码速查](#5-错误与状态码速查)

---

## 0. 通用约定

- **Base URL**：`/api/v1`
- **请求体**：`application/json`（除文件上传为 `multipart/form-data`）
- **错误响应**（非 SSE）：`{ "detail": "<message>" }`；参数校验失败为 FastAPI
  默认 `422` 形状 `{ "detail": [{ "loc": [...], "msg": "...", "type": "..." }] }`
- **时间戳有两种格式，注意区分**：
  - 会话/消息记录（`ConversationRecord` / `MessageRecord`）的
    `created_at` / `updated_at`：**ISO 8601 字符串**（如 `2026-08-26T11:05:00`）
  - `chat-messages` 请求/响应/SSE 帧里的 `created_at`：**整数 Unix 秒**
    （如 `1720000000`），前端用 `new Date(created_at * 1000)` 转换
- **认证**：当前无鉴权；`assistant` 选择见 §1.2

---

## 1. 对话 `POST /chat-messages`（核心）

`POST /api/v1/chat-messages`

会话缺省自动创建，续聊带 `conversation_id`。

### 1.1 请求体

```json
{
  "query": "帮我找高速背板连接器的潜在客户",
  "response_mode": "streaming",
  "conversation_id": "",
  "agent_id": "discover"
}
```

| 字段 | 类型 | 默认 | 约束 | 说明 |
|---|---|---|---|---|
| `query` | string | — | 必填，1–4000 字符 | 用户输入 |
| `response_mode` | string | `"streaming"` | `"streaming"` / `"blocking"` | `streaming`=SSE 流式；`blocking`=一次返回 JSON |
| `conversation_id` | string | `""` | — | 空串自动创建会话；续聊传上次响应的会话 ID（不存在 → 404） |
| `agent_id` | string | `""` | ≤100 字符 | 显式助手选择，见 §1.2 |

> 前端建议：发消息时始终带上当前选中的 `agent_id`（首轮用于绑定，续聊用于
> 切换）；未选中则**不传**，即默认通用对话。切回通用对话传 `agent_id="generic"`。

### 1.2 agent_id 语义（显式选择助手）

| 场景 | 传值 | 行为 |
|---|---|---|
| 首轮（`conversation_id` 空） | 专家 id（如 `discover`） | 创建会话并绑定该专家 |
| 首轮 | 不传 / 空串 | 创建会话，走通用对话 |
| 续聊 | 不传 / 空串 | 沿用会话已绑定的助手 |
| 续聊（切换助手） | 新的专家 id 或 `"generic"` | 重新绑定 / 切回通用对话 |
| 任意 | 未知 id | **404** `{ "detail": "未知助手：<id>" }` |

`"generic"` 是保留字（对应内置通用对话），不属目录。**选助手没有单独接口**，
随下一次 `/chat-messages` 生效。

### 1.3 响应头

两种模式都返回：

| 响应头 | 说明 |
|---|---|
| `X-Conversation-Id` | 本次会话 ID；自动创建时客户端**凭此续聊** |

`streaming` 额外返回：

| 响应头 | 值 | 说明 |
|---|---|---|
| `Content-Type` | `text/event-stream` | SSE 流 |
| `Cache-Control` | `no-cache` | 禁用缓存 |
| `X-Accel-Buffering` | `no` | 禁用反向代理缓冲（否则整条流积压到结束才下发） |

### 1.4 blocking 模式响应（200 JSON）

`response_mode="blocking"` 时返回 chat-messages 形状：

```json
{
  "message_id": "deadbeefdeadbeefdeadbeefdeadbeef",
  "mode": "chat",
  "answer": "已为您找到 5 家成都线缆厂……",
  "metadata": {
    "usage": {
      "prompt_tokens": 12000,
      "completion_tokens": 800,
      "total_tokens": 12800,
      "cached_read_tokens": 9000,
      "cached_write_tokens": 1200
    },
    "assistant": { "type": "expert", "id": "discover" }
  },
  "conversation_id": "cafebabecafebabecafebabecafebabe",
  "created_at": 1720000000
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `message_id` | string | 本回合消息 ID（历史接口与 SSE 帧引用同一 ID） |
| `mode` | string | 固定 `"chat"` |
| `answer` | string | 助手最终正文 |
| `metadata.usage` | object | 5 键 tokens 用量（见 §5） |
| `metadata.assistant` | object? | 当前生效助手 `{type, id}`；未绑定（通用/新会话）时**键可能不出现** |
| `conversation_id` | string | 会话 ID（续聊用） |
| `created_at` | int | Unix 秒 |

### 1.5 streaming 模式响应（SSE 流结构）

`response_mode="streaming"` 时返回 **SSE 事件流**。这是前端最重要的部分，注意：
**事件判别字段 `event` 在 JSON 载荷内部**，不在 SSE 的 `event:` 行——每个帧格式为：

```
data: {json}\n\n
```

（即一行 `data: ` 前缀 + JSON + 两个换行。没有 `[DONE]` 哨兵，流以 `message_end`
帧收尾。）

#### 帧类型总览

| `event` | 含义 | 前端表现 |
|---|---|---|
| `message` | 正文增量（打字机） | 追加到正文区 |
| `thinking_started` | 思考开始 | 打开折叠的思考分区 |
| `thinking_delta` | 思考增量 | 思考分区追加 |
| `thinking_ended` | 思考结束 | 折叠思考分区（可展示耗时） |
| `message_end` | **收尾帧** | 回合结束，恢复输入框 |
| `ping` | 心跳 | 忽略 |
| `error` | 错误 | 错误展示 |

#### 帧字段详解

**`message` — 正文增量**（一条内容分多帧到达，前端逐帧追加；服务端已做打字机
节流，帧间隔均匀）

```json
{
  "event": "message",
  "message_id": "deadbeefdeadbeefdeadbeefdeadbeef",
  "conversation_id": "cafebabecafebabecafebabecafebabe",
  "answer": "已为您找到 ",
  "created_at": 1720000000
}
```

| 字段 | 说明 |
|---|---|
| `answer` | 本次增量文本片段（拼接所有 `message` 帧即最终正文） |

**`thinking_started` — 思考开始**（DeepSeek 式思考分区）

```json
{
  "event": "thinking_started",
  "message_id": "deadbeefdeadbeefdeadbeefdeadbeef",
  "conversation_id": "cafebabecafebabecafebabecafebabe",
  "created_at": 1720000000
}
```

**`thinking_delta` — 思考增量**（注意字段名是 `content`，不是 `answer`）

```json
{
  "event": "thinking_delta",
  "message_id": "deadbeefdeadbeefdeadbeefdeadbeef",
  "conversation_id": "cafebabecafebabecafebabecafebabe",
  "content": "先圈定成都地区，再按产品线评分……",
  "created_at": 1720000000
}
```

**`thinking_ended` — 思考结束**

```json
{
  "event": "thinking_ended",
  "message_id": "deadbeefdeadbeefdeadbeefdeadbeef",
  "conversation_id": "cafebabecafebabecafebabecafebabe",
  "duration_ms": 3450,
  "created_at": 1720000000
}
```

**`message_end` — 收尾帧**（流到此结束，之后不再有数据；无 `[DONE]`）

```json
{
  "event": "message_end",
  "message_id": "deadbeefdeadbeefdeadbeefdeadbeef",
  "conversation_id": "cafebabecafebabecafebabecafebabe",
  "metadata": {
    "usage": {
      "prompt_tokens": 12000,
      "completion_tokens": 800,
      "total_tokens": 12800,
      "cached_read_tokens": 9000,
      "cached_write_tokens": 1200
    },
    "assistant": { "type": "expert", "id": "discover" }
  },
  "created_at": 1720000000
}
```

- `metadata.usage`：本回合 5 键 tokens 用量
- `metadata.assistant`：`{type, id}`，未绑定时键可能不出现

**`ping` — 心跳**（保活；服务端周期发送，周期小于代理超时）

```json
{ "event": "ping" }
```

**`error` — 错误帧**（回合中途失败，流会随后结束）

```json
{
  "event": "error",
  "status": 500,
  "code": "server",
  "message": "内部错误"
}
```

| 字段 | 说明 |
|---|---|
| `status` | HTTP 状态码（多数为 500） |
| `code` | 错误分类，见 §5 |
| `message` | 已脱敏的错误信息 |

#### 流结构要点

1. **思考与正文分轨**：思考增量**绝不进入** `message` 帧的 `answer`，独立经
   `thinking_*` 帧推送。前端据此渲染思考分区（可折叠），正文只拼 `message` 帧。
2. **打字机节流在服务端**：帧按固定节奏下发，「已推送」即「已显示」；前端直接
   逐帧 `append` 即可，无需自己再节流。长回答有追赶机制，不会严重滞后。
3. **正常收尾**：收到 `message_end` 即本回合结束，此后流关闭。此时可恢复输入框、
   刷新历史。
4. **错误收尾**：收到 `error` 帧后流即结束；该回合历史落库 `status=error`。
5. **心跳**：`ping` 帧前端直接忽略。
6. **客户端断开**：前端关闭连接/取消请求即止；服务端会取消图执行并释放会话资源。
   恢复后凭 `conversation_id` 续聊（已产生的正文在历史接口中可取）。
7. **逐帧拼装**：正文 = 所有 `message` 帧 `answer` 拼接；思考 = 所有 `thinking_delta`
   帧 `content` 拼接。`message_end.metadata.usage` 为整回合用量。

#### 前端接入建议（fetch + ReadableStream）

- 用 `fetch` + `response.body.getReader()` 按行读 SSE 帧，或直接用
  `EventSource` 的 `onmessage` 拿 `data` 再 `JSON.parse`（`event` 在 JSON 内）。
- 记录响应头 `X-Conversation-Id`，用于下一轮续聊。
- 以收到 `message_end`（或 `error`）作为单回合结束信号，不要依赖流关闭。

---

## 2. 文件接口

### 2.1 上传限制配置

`GET /api/v1/files/upload`

**响应 200**：

```json
{
  "file_size_limit": 20971520,
  "file_type_limit": ["png", "jpg", "jpeg", "gif", "webp", "pdf", "docx", "xlsx", "csv", "md", "txt"]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `file_size_limit` | int | 单文件大小上限（字节）；前端上传前校验 |
| `file_type_limit` | string[] | 允许的扩展名（不含点）；前端文件选择过滤 |

### 2.2 上传文件

`POST /api/v1/files/upload`

请求体：`multipart/form-data`，字段名 **`file`**（`<input type="file" name="file">`）。

**响应 200**：

```json
{
  "file_id": "0123456789abcdef0123456789abcdef",
  "name": "产品资料.pdf",
  "media_type": "application/pdf",
  "size_bytes": 1048576,
  "created_at": "2026-08-26T11:20:00"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `file_id` | string | 文件 ID（预览用） |
| `name` | string | 原始文件名 |
| `media_type` | string | MIME 类型 |
| `size_bytes` | int | 大小 |
| `created_at` | string | ISO 8601 |

**错误**：`400` 文件超过 `file_size_limit` 或扩展名不在 `file_type_limit` 内。

> 前端上传前先调 `GET /files/upload` 拿限制做本地校验，减少无效上传。

### 2.3 文件预览（流式）

`GET /api/v1/files/{file_id}/preview`

**响应**：
- `200`：字节流，`Content-Type` = 文件 `media_type`，`Content-Disposition: inline`
  （浏览器可直接展示图片/PDF）
- `404`：文件不存在

使用场景：
- 图片/PDF/文档：`<img src>` / iframe / 新窗口直接打开该 URL
- 下载：`<a href="...preview" download>` 或用 fetch 取 blob（服务端为 inline，
  需前端加 `download` 属性才触发下载）

> 预览即标记文件 `used=true`（供服务端清理未使用文件）。

---

## 3. 会话接口

### 3.1 会话列表

`GET /api/v1/conversations`

| 参数 | 位置 | 类型 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | query | int | 50 | 每页条数（1–200） |
| `offset` | query | int | 0 | 偏移量 |

**响应 200**：`ConversationRecord[]`（按 `updated_at` 倒序）

```json
[
  {
    "conversation_id": "cafebabecafebabecafebabecafebabe",
    "agent_id": "finder",
    "model_provider": "qwen3.7-max",
    "model_id": "qwen3.7-max",
    "name": "找潜在客户，帮我搜一下成都的线缆厂",
    "summary": null,
    "status": "active",
    "dialogue_count": 5,
    "created_at": "2026-08-26T11:00:00",
    "updated_at": "2026-08-26T11:10:00"
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `conversation_id` | string | 会话 ID（续聊时传给 `/chat-messages`） |
| `agent_id` | string? | 路由命中的智能体（首轮后绑定） |
| `model_provider` / `model_id` | string? | 生效模型快照 |
| `name` | string | 会话标题（首条 query 截断，50 字内） |
| `summary` | string? | 摘要（预留，当前为 null） |
| `status` | `"active"` / `"closed"` | 会话状态 |
| `dialogue_count` | int | 回合数 |
| `created_at` / `updated_at` | string | ISO 8601 |

### 3.2 会话消息流

`GET /api/v1/conversations/{conversation_id}/messages`

| 参数 | 位置 | 类型 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | query | int | 50 | 每页条数（1–200） |
| `offset` | query | int | 0 | 偏移量 |

**响应 200**：`MessageRecord[]`（按 `created_at` 升序，即时间正序）

```json
[
  {
    "message_id": "deadbeefdeadbeefdeadbeefdeadbeef",
    "conversation_id": "cafebabecafebabecafebabecafebabe",
    "agent_id": "finder",
    "provider": "qwen3.7-max",
    "model": "qwen3.7-max",
    "query": "帮我找 5 家成都线缆厂",
    "answer": "已为您找到 5 家……",
    "thinking": "先圈定成都地区，再按产品线评分……",
    "status": "normal",
    "error": null,
    "latency_ms": 12340,
    "prompt_tokens": 12000,
    "completion_tokens": 800,
    "total_tokens": 12800,
    "cached_read_tokens": 9000,
    "cached_write_tokens": 1200,
    "created_at": "2026-08-26T11:05:00",
    "updated_at": "2026-08-26T11:05:00"
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `message_id` | string | 消息 ID（与 SSE 帧 / blocking 响应的 `message_id` 一致） |
| `conversation_id` | string | 归属会话 |
| `agent_id` | string? | 回合归属智能体 |
| `provider` / `model` | string? | 生效模型快照 |
| `query` | string | 用户输入 |
| `answer` | string? | 助手最终正文 |
| `thinking` | string? | 思考内容（审计用途；前端可折叠展示，不参与上下文） |
| `status` | `"normal"` / `"error"` | 回合状态；error 时 `answer` 可能为空 |
| `error` | string? | 错误信息（仅 error 回合非空） |
| `latency_ms` | int | 回合耗时（毫秒） |
| `prompt_tokens` | int | 输入 tokens（回合聚合） |
| `completion_tokens` | int | 输出 tokens（回合聚合） |
| `total_tokens` | int | 总 tokens |
| `cached_read_tokens` | int | 缓存命中 tokens |
| `cached_write_tokens` | int | 缓存写入 tokens |
| `created_at` / `updated_at` | string | ISO 8601 |

> 翻页建议：会话消息可能很多，用 `limit=50` + 递增 `offset` 从前往后翻；历史长时
> 也可先取最后一页倒序加载。

### 3.3 删除会话（软删除）

`DELETE /api/v1/conversations/{conversation_id}`

**软删除**：标记 `is_delete=true`，conversation 与 messages 行保留（token 用量可
审计），仅从列表隐藏且不可续聊；同时释放内存会话与运行时。业务状态
`status`（active/closed）不随删除覆盖，可还原。

**响应**：
- `204`：删除成功（空体）
- `404`：`{ "detail": "未知会话：<id>" }`（会话不存在或已删除）

> 前端删除会话列表项时调用；`204` 与 `404` 均按「已删除」处理并从本地列表移除，
> 其他错误保留条目（避免误删后刷新又被后端带回）。

---

## 4. 助手目录

`GET /api/v1/assistants`

列出用户可选助手：**专家**；通用对话为默认态，**不列入目录**。

**响应 200**：

```json
[
  {
    "id": "discover",
    "type": "expert",
    "name": "客户发现",
    "description": "为电子信息产业链销售寻找潜在客户，输出八维量化评分与专业客户发现报告",
    "capabilities": ["client-finder"]
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 助手标识，即传给 `/chat-messages` 的 `agent_id` |
| `type` | `"expert"` | 专家（agents/ 包，类 Claude Code 的工具型） |
| `name` | string | 展示名（选择器直接展示） |
| `description` | string | 一句话职责（选择器副标题） |
| `capabilities` | string[] | 能力标签（专家取其技能 ID） |

> 类型体系：目录只列 `expert`。`generic`（内置通用对话）是默认态——未指定
> `agent_id` 即走通用对话，不出现在目录。前端在聊天页加载时拉取一次；建议每次
> 进入页面刷新（热重载后内容可能变化）。

---

## 5. 错误与状态码速查

### usage 五键

| 键 | 说明 |
|---|---|
| `prompt_tokens` | 输入 tokens |
| `completion_tokens` | 输出 tokens |
| `total_tokens` | 总 tokens |
| `cached_read_tokens` | 缓存命中（读缓存）tokens |
| `cached_write_tokens` | 缓存写入（建缓存）tokens |

### metadata.assistant

| 取值 | 含义 |
|---|---|
| `{"type":"expert","id":"discover"}` | 已绑定专家 |
| `{"type":"generic","id":null}` | 通用对话 |
| 键不出现 | 新会话未绑定（相当于通用） |

前端可用它回显选择器状态；键缺失时选择器为空态（默认通用）。

### HTTP 状态码

| 状态码 | 场景 |
|---|---|
| `200` | 成功 |
| `204` | 删除成功（空体） |
| `400` | 请求非法（文件超限/类型不符、`query` 为空等）；错误码 `bad_request` |
| `404` | 未知助手 / 未知会话 / 文件不存在；错误码 `not_found` |
| `401` | 鉴权失败；错误码 `auth` |
| `403` | 审批被拒；错误码 `denied` |
| `422` | 参数校验失败（FastAPI 默认形状） |
| `500` | 服务端/上游错误（多数错误码兜底） |

### SSE `error` 帧 `code` 取值

| `code` | 含义 | 是否可重试 |
|---|---|---|
| `not_found` | 资源不存在 | 否 |
| `bad_request` | 请求非法 | 否 |
| `invalid_argument` | 工具/参数非法 | 否 |
| `auth` | 鉴权失败 | 否 |
| `denied` | 操作被拒 | 否 |
| `content_filter` | 内容过滤 | 否 |
| `connection` | 连接失败 | 是 |
| `timeout` | 超时 | 是 |
| `rate_limit` | 限流 | 是（退避后重试） |
| `server` | 服务端/上游 5xx | 视情况 |
| `stream_interrupted` | 流中断（已产出一部分，重试会导致重复输出） | 否 |
| `config` / `script` / `mcp` | 配置 / 脚本 / MCP 相关 | 视情况 |

> 前端提示建议：`rate_limit` / `timeout` / `connection` 可提示「稍后重试」；
> `content_filter` 提示「内容不合规，请调整表述」；其余按「请求失败」处理。
