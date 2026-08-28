# 平台 API 文档（助手选择 + 历史记录 + 文件系统）

> 供前端实现功能对照。所有接口前缀 `/api/v1`；除特殊说明外请求/响应均为
> JSON（`Content-Type: application/json`）。`created_at`/`updated_at` 为
> ISO 8601 字符串（pydantic 序列化）。错误统一为 `{detail: <message>}` 形状。

## 目录

- [1. 会话接口](#1-会话接口)
- [2. 文件接口](#2-文件接口)
- [3. 对话接口变更（usage 追加字段）](#3-对话接口变更usage-追加字段)
- [4. 已移除接口](#4-已移除接口)
- [5. 字段速查表](#5-字段速查表)
- [6. 助手选择（新增：显式选择取代 LLM 自动路由）](#6-助手选择新增显式选择取代-llm-自动路由)

---

## 1. 会话接口

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

### 1.3 删除会话

`DELETE /api/v1/conversations/{conversation_id}`

**软删除**：将会话标记为 `is_delete=true`，conversation 与 messages 行保留
（token 用量可审计），仅从 `GET /conversations` 列表隐藏；同时释放内存会话与
运行时（MCP 引用），删除后不可续聊。业务状态 `status`（active/closed）不随
删除覆盖，可还原。DB 历史与内存会话皆不存在（或已删除）→ 404。

**响应**：
- `204`：删除成功（空体）
- `404`：会话不存在或已删除 `{detail: "未知会话：<id>"}`

> 前端删除会话列表项时调用本接口；`204` 与 `404` 均按「已删除」处理并从本地
> 列表移除，其他错误保留条目（避免误删后刷新又被后端带回）。

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

---

## 6. 助手选择（新增：显式选择取代 LLM 自动路由）

> 平台不再让模型自动识别智能体。前端需在聊天页提供「助手选择器」：用户显式选中
> 某个**专家**，经 `agent_id` 绑定到会话；未选中任何助手时走**通用对话**（默认态）。
> 这是「智能体多了会误路由」的解法——选择权交给用户，不交给模型。

### 6.1 助手目录

`GET /api/v1/assistants` — 用户可选的助手清单（聚合：专家；通用对话为默认态，不列入目录）。

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

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 助手标识，即传给 `/chat-messages` 的 `agent_id` |
| `type` | `"expert"` | 专家（agents/ 包，类 Claude Code 的工具型）；目录不返回通用对话 |
| `name` | string | 展示名（选择器直接展示） |
| `description` | string | 一句话职责（选择器副标题） |
| `capabilities` | string[] | 能力标签（专家取其技能 ID，如 `client-finder`） |

**类型体系**：目录只列 `expert`（复杂工具包，来自 agents/ 包）。`generic`（内置通用
对话）是**默认态**——未指定 `agent_id` 时即走通用对话，不出现在目录。未来的「简单
技能」（如天气问答的纯 prompt 型）**不属本接口的 agent 类型**，届时另行扩展，前端
无需为它预判结构。

> 前端在聊天页加载时拉取一次即可；热重载后内容可能变化（如新增专家），建议每次进入页面刷新。

### 6.2 对话请求显式选择

`POST /api/v1/chat-messages` 请求体新增**可选**字段 `agent_id`：

```json
{
  "query": "帮我找高速背板连接器的潜在客户",
  "response_mode": "streaming",
  "conversation_id": "",
  "agent_id": "discover"
}
```

`agent_id` 语义：

| 场景 | 传值 | 行为 |
|---|---|---|
| 首轮（`conversation_id` 空） | 某个专家 id（如 `discover`） | 创建会话并绑定该专家 |
| 首轮 | 不传 / 空串 | 创建会话，走通用对话 |
| 续聊 | 不传 / 空串 | 沿用会话已绑定的助手 |
| 续聊（切换助手） | 新的专家 id 或 `"generic"` | 重新绑定 / 切回通用对话 |
| 任意 | 未知 id | **404** `{detail: "未知助手：<id>"}` |

**`"generic"` 是保留字**（对应默认通用对话），用于把会话从专家切回通用对话。

前端建议：用户选中专家后**每次发消息都带上当前选中的 `agent_id`**（首轮用于绑定，
续聊用于切换）；未选中（或不传 `agent_id`）即默认通用对话，切回通用对话可传
`agent_id="generic"`。选助手**不需要单独的接口**——它随下一次 `/chat-messages` 生效。

### 6.3 响应中的 `metadata.assistant`

blocking 响应与 SSE `message_end` 帧的 `metadata` 新增 `assistant` 字段，反映**当前回合生效的助手**：

```json
{
  "usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_read_tokens": 0, "cached_write_tokens": 0 },
  "assistant": { "type": "expert", "id": "discover" }
}
```

| `assistant` 取值 | 含义 |
|---|---|
| `{"type":"expert","id":"discover"}` | 已绑定专家 |
| `{"type":"generic","id":null}` | 通用对话 |
| 键不出现 | 新会话未绑定（相当于通用） |

前端可用它回显选择器状态；`assistant` 键缺失时选择器为空态（默认通用）。

### 6.4 移除的旧机制

- LLM 自动路由工具（`select_agent` / `select_skill`）已移除：模型不再决定进入哪个助手。
- 聊天页不再需要「让模型猜你要哪个智能体」的提示文案；改为用户显式选择。
