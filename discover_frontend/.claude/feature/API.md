# API 契约 — discover_backend（前端唯一消费面）

> 前端**只消费以下已有接口，不新增后端接口**。类型定义集中于 `src/types.ts`（映射后端 pydantic 模型），
> 禁止在组件内散落重复定义。Base URL：`VITE_API_BASE_URL`（含 `/api/v1` 前缀，默认 `/api/v1`）。

## 1. 会话历史（会话列表唯一事实源在后端）

### `GET /conversations?limit=&offset=`

会话列表，按 `updated_at` 倒序返回（前端再排序一次兜底）。

```ts
interface ConversationRecord {
  conversation_id: string
  agent_id: string | null        // 绑定助手（专家 id）；未绑定 = null
  model_provider: string | null
  model_id: string | null
  name: string                   // 会话标题（首条 query 截断，50 字内）
  summary: string | null         // 预留，当前为 null
  status: 'active' | 'closed'
  dialogue_count: number
  created_at: string
  updated_at: string
}
```

### `GET /conversations/{id}/messages?limit=&offset=`

单条回合记录（query + answer 同行）。

```ts
interface MessageRecord {
  message_id: string
  conversation_id: string
  agent_id: string | null
  provider: string | null
  model: string | null
  query: string
  answer: string | null
  thinking: string | null       // 思考内容（审计用途；前端可折叠展示）
  status: 'normal' | 'error'
  error: string | null
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_read_tokens: number
  cached_write_tokens: number
  created_at: string
  updated_at: string
}
```

前端映射：一条 `MessageRecord` → 用户气泡（`{id}:user`）+ 助手气泡（`message_id`）两条。

### `DELETE /conversations/{id}`

软删除。`204` 成功；`404` 视为已删除；其余错误保留条目。

## 2. 文件

### `GET /files/upload`

上传限制配置（前端本地校验用）。

```ts
interface UploadConfig {
  file_size_limit: number        // 字节
  file_type_limit: string[]      // 扩展名数组（无点），如 ['png','pdf']
}
```

### `POST /files/upload`

multipart/form-data，字段名 `file`。返回：

```ts
interface UploadedFile {
  file_id: string
  name: string
  media_type: string
  size_bytes: number
  created_at: string
}
```

### `GET /files/{file_id}/preview`

流式 inline 预览。浏览器直接展示；前端加 `download` 属性才触发下载。预览仅限图片缩略 /
新窗口打开，禁止将文件内容作为 HTML 内联渲染。

## 3. 助手目录

### `GET /assistants`

用户可选助手清单（聚合：专家 + 内置通用对话）。聊天页加载时拉取一次。

```ts
interface AssistantRecord {
  id: string          // 传给 /chat-messages 的 agent_id；'generic' 为保留字（通用对话）
  type: 'expert' | 'generic'
  name: string
  description: string
  capabilities: string[]
}
```

## 4. 对话

### `POST /chat-messages`

请求体：

```ts
interface ChatRequest {
  query: string
  response_mode: 'streaming' | 'blocking'
  conversation_id: string   // 空串 = 新建会话；续聊必带后端回传的会话 ID
  agent_id?: string         // 显式选择助手；空串省略不传（首轮走通用 / 续聊沿用已绑定）
}
```

#### 响应（streaming）—— SSE

- 响应头 `X-Conversation-Id` 携带会话 ID（**优先级最高**），帧内 `conversation_id` 兜底。
- `data:` 行按空行分隔为帧；帧 JSON 的 `event` 字段判别类型，共 7 种（见 `REQUIREMENTS.md` §4）。
- `message_end` 为终止帧，**流结束，无 `[DONE]`**。载荷含 `metadata`（v2 终态契约）：

```ts
interface TurnMetadata {
  status?: 'succeeded' | 'partial' | 'cancelled'  // RunStatus；cancelled = 用户 stop
  reason?: string                                  // 终止原因：completed / no_progress / token_budget / contract_failed / user_cancelled 等
  limitations?: string[]
  unfinished_phases?: string[]
  usage?: {                                        // TurnRecorder.compat_usage 兼容 5 键
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    cached_read_tokens: number
    cached_write_tokens: number
  }
  phase?: { phase: 'waiting_input'; question?: string; missing_fields?: string[] }  // RunInputRequested 暂停通知
  assistant?: { type: 'expert' | 'generic'; id: string | null }  // 当前回合生效助手
}
```

- `RunCancelled`（用户 stop）→ `message_end` 且 `metadata.status="cancelled"`；`RunFailed` → `error` 帧，不落 `message_end`。

#### 响应（blocking）—— JSON

```ts
interface BlockingChatResponse {
  message_id: string
  mode: 'chat'
  answer: string
  metadata: TurnMetadata
  conversation_id: string
  created_at: number
}
```

`blocking` 不推思考帧。

## 5. 错误形状（统一映射源，见 `src/lib/errors.ts`）

| 来源 | 形状 |
|---|---|
| 后端业务错误 | `{ error: { category: string, message: string } }` |
| FastAPI 校验 | `{ detail: string }` |
| 兜底 | `{ message: string }` |
| SSE error 帧 | `{ status: number, code: string, message: string }` |

HTTP 状态码 → 前端文案映射（400 请求参数有误 / 401 未授权 / 403 无权限 / 404 会话不存在 /
429 过于频繁 / 500 服务内部错误 / 502 网关错误 / 503 暂不可用）。
