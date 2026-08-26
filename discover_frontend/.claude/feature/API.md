# 平台 API 文档（历史记录 + 文件系统）

> 供前端实现功能对照。所有接口前缀 `/api/v1`；除特殊说明外请求/响应均为
> JSON（`Content-Type: application/json`）。`created_at`/`updated_at` 为
> ISO 8601 字符串（pydantic 序列化）。错误统一为 `{detail: <message>}` 形状。

## 目录

- [1. 历史记录接口](#1-历史记录接口)
- [2. 文件接口](#2-文件接口)
- [3. 对话接口变更（usage 追加字段）](#3-对话接口变更usage-追加字段)
- [4. 已移除接口](#4-已移除接口)
- [5. 字段速查表](#5-字段速查表)

---

## 1. 历史记录接口

### 1.1 会话列表

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

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `conversation_id` | string | 会话 ID（即续聊时传给 `/chat-messages` 的 `conversation_id`） |
| `agent_id` | string? | 路由命中的智能体（首轮后绑定） |
| `model_provider` / `model_id` | string? | 生效模型快照 |
| `name` | string | 会话标题（首条 query 截断，50 字内） |
| `summary` | string? | 摘要（预留，当前为 null） |
| `status` | "active" \| "closed" | 会话状态 |
| `dialogue_count` | int | 回合数 |

---

### 1.2 会话消息流

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

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `message_id` | string | 消息 ID（SSE 流中 message/message_end 帧的 `message_id`） |
| `conversation_id` | string | 归属会话 |
| `agent_id` | string? | 回合归属智能体 |
| `provider` / `model` | string? | 生效模型快照 |
| `query` | string | 用户输入（每个回合一行，query+answer 同行） |
| `answer` | string? | 助手最终正文 |
| `thinking` | string? | 思考内容（审计用途；前端可折叠展示，不参与上下文） |
| `status` | "normal" \| "error" | 回合状态；error 时 `answer` 可能为空 |
| `error` | string? | 错误信息（仅 error 回合非空） |
| `latency_ms` | int | 回合耗时（毫秒） |
| `prompt_tokens` | int | 输入 tokens（回合聚合） |
| `completion_tokens` | int | 输出 tokens（回合聚合） |
| `total_tokens` | int | 总 tokens |
| `cached_read_tokens` | int | 缓存命中 tokens（聚合） |
| `cached_write_tokens` | int | 缓存写入 tokens（聚合） |

> 翻页：会话消息可能很多，建议 `limit=50` 倒序加载（先拿最新，再向前翻）。

---

### 1.3 会话用量汇总

`GET /api/v1/conversations/{conversation_id}/usage`

**响应 200**：

```json
{
  "message_count": 5,
  "prompt_tokens": 60000,
  "completion_tokens": 4000,
  "total_tokens": 64000,
  "cached_read_tokens": 45000,
  "cached_write_tokens": 6000
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `message_count` | int | 回合数 |
| `prompt_tokens` / `completion_tokens` / `total_tokens` | int | 会话级聚合 |
| `cached_read_tokens` / `cached_write_tokens` | int | 会话级缓存命中/写入聚合 |

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
| `file_size_limit` | int | 单文件大小上限（字节）；前端用于上传前校验 |
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
| `file_id` | string | 文件 ID（预览/后续消息引用用） |
| `name` | string | 原始文件名 |
| `media_type` | string | MIME 类型 |
| `size_bytes` | int | 大小 |
| `created_at` | string | 上传时间 |

**错误**：
- `400`：文件超过 `file_size_limit` 或扩展名不在 `file_type_limit` 内

> 前端上传前建议先调 `GET /files/upload` 拿限制做本地校验，减少无效上传。

### 2.3 文件预览（流式）

`GET /api/v1/files/{file_id}/preview`

**响应**：
- `200`：字节流，`Content-Type` = 文件的 `media_type`，`Content-Disposition: inline`（浏览器可直接展示图片/PDF）
- `404`：文件不存在

使用场景：
- 图片/PDF/文档：前端 `<img src>` / iframe / 新窗口直接打开该 URL 即可
- 下载：`<a href="...preview" download>` 或用 fetch 取 blob（服务端为 inline，需前端加 download 属性才触发下载）

> 预览即标记文件 `used=true`（供服务端清理未使用文件）。

---

## 3. 对话接口变更（usage 追加字段）

`POST /api/v1/chat-messages` 的响应/SSE 帧中 `metadata.usage` 由 3 键扩展为 5 键：

```json
{
  "prompt_tokens": 12000,
  "completion_tokens": 800,
  "total_tokens": 12800,
  "cached_read_tokens": 9000,
  "cached_write_tokens": 1200
}
```

- **blocking**：`ChatMessageResponse.metadata.usage`
- **streaming**：`message_end` 帧的 `metadata.usage`

新增两键：
| 键 | 说明 |
|---|---|
| `cached_read_tokens` | 缓存命中（读缓存）tokens |
| `cached_write_tokens` | 缓存写入（建缓存）tokens |

**产物事件变化**：SSE 的 `artifact_ready` 事件里 `download_url` 由
`/sessions/{sid}/artifacts/{aid}` 改为 **`/files/{file_id}/preview`**（相对 `/api/v1` 基础
路径，前端按现有习惯拼 `/api/v1` 后直接预览/下载）。

---

## 4. 已移除接口

| 原接口 | 替代 |
|---|---|
| `GET /api/v1/sessions/{session_id}/artifacts/{artifact_id}`（产物下载） | `GET /api/v1/files/{file_id}/preview` |

产物不再按会话归属隔离（注册表全局可预览，凭 uuid `file_id` 不可枚举）。

---

## 5. 字段速查表

| 枚举 | 取值 |
|---|---|
| `status`（会话） | `active` / `closed` |
| `status`（消息） | `normal` / `error` |
| `ConversationRecord` 必填 | `conversation_id`, `name`, `status`, `dialogue_count`, `created_at`, `updated_at` |
| `MessageRecord` 必填 | `message_id`, `conversation_id`, `query`, `status`, `latency_ms`, token 五字段, `created_at`, `updated_at` |
| 分页 | `limit`（1–200，默认 50）、`offset`（默认 0） |
