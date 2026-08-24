# discover_frontend 需求说明（v1）

> 目标：模仿 ChatGPT 页面，基于后端多智能体承载平台已有 API，实现单用户对话功能。
> 后端契约以 `discover_backend` 为准（`POST /api/v1/chat-messages`、`GET /api/v1/sessions/{sid}/artifacts/{aid}`）。

## 1. 产品目标与边界

* **在**：ChatGPT 风格对话页 + 会话侧边栏 + 流式打字机 + Markdown 渲染 + 高级事件（思考/工具/产物）展示。
* **不在（v1 明确不做）**：登录鉴权、多用户、后端新增接口、会话改名、模型切换 UI、文件上传。

## 2. 功能点清单

### 2.1 对话（核心）
| # | 功能 | 说明 |
|---|---|---|
| F1 | 发送消息 | 输入框 `Enter` 发送，`Shift+Enter` 换行；`query` 长度 ≤ 4000（后端上限，前端同样校验并提示） |
| F2 | 流式回复 | `POST /chat-messages`，`response_mode=streaming`，`fetch` 流式读 SSE，逐帧追加正文，打字机效果 |
| F3 | 会话自动创建 | 首次发送 `conversation_id=""`，后端自动建会话；从响应头 `X-Conversation-Id`（优先）/ 响应体取回会话 ID 并存入 store |
| F4 | 续聊 | 后续发送携带当前会话 ID，后端复用会话状态（历史服务端持有） |
| F5 | 停止生成 | 发送中可停止：`AbortController.abort()`，同步复位流式状态，保留已收内容 |
| F6 | 阻塞兜底 | 流式失败时可切换 `response_mode=blocking`（环境开关 + 手动重试路径），返回 JSON `{message_id, answer, metadata, conversation_id, created_at}` |
| F7 | 错误态 | SSE `error` 帧 / HTTP 非 2xx → 消息气泡错误态 + 可读文案；错误体 `{error:{category,message}}` 与 `{status,code,message}` 统一映射 |

### 2.2 会话侧边栏
| # | 功能 | 说明 |
|---|---|---|
| S1 | 会话列表 | 展示本地持久化的会话（`conversation_id` + `title` + `updated_at`） |
| S2 | 新建会话 | 清空当前输入与消息区，重置会话 ID；进入待发送状态 |
| S3 | 切换会话 | 点击切换展示该会话本地消息快照；无快照时提示空会话（后端无历史查询接口） |
| S4 | 删除会话 | 删除本地记录（仅前端，无后端删除接口）；当前会话被删则复位到空会话 |
| S5 | 本地持久化 | `localStorage` key 前缀 `disf_`；写入失败降级内存态（隐私模式） |

### 2.3 消息渲染
| # | 功能 | 说明 |
|---|---|---|
| M1 | Markdown | `markdown-it` 渲染回复；代码块 `highlight.js` 高亮；渲染结果必须 `DOMPurify.sanitize` |
| M2 | 思考块 | `thinking_started` / `thinking_delta` / `thinking_ended` 事件 → 折叠的「思考」块，流式追加 `text`，可展开/收起；默认收起 |
| M3 | 工具调用卡 | `tool_call_started`（工具名 + 参数摘要）→ 进行中；`tool_call_completed`（`ok`、结果摘要、耗时）→ 完成/失败态；`gate_checked` 失败提示 |
| M4 | 产物链接 | `artifact_ready` → 可下载链接（文件名 + 大小），指向 `GET /api/v1/sessions/{sid}/artifacts/{aid}`，`a[download]` 下载 |
| M5 | 用量展示 | `message_end.metadata.usage`（`prompt_tokens`/`completion_tokens`/`total_tokens`）→ 消息角标或页脚轻量展示 |
| M6 | 复制 | 消息区「复制」按钮复制纯文本 |

### 2.4 交互与 UI（ChatGPT 风格）
| # | 功能 | 说明 |
|---|---|---|
| U1 | 布局 | 左侧窄侧边栏（会话列表 + 新建按钮），右侧对话区（消息流 + 底部输入区） |
| U2 | 空态 | 无消息时居中欢迎语 + 提示输入，ChatGPT 首页风格 |
| U3 | 输入态 | 发送中禁用发送、显示「停止」；输入框自适应高度 |
| U4 | 响应式 | 窄屏（<768px）侧边栏抽屉式折叠，保持可用 |

## 3. SSE 事件处理表（后端契约）

流以 `message_end` 收尾，**无 `[DONE]`**；`data:` 帧按空行分隔，`event` 字段判别。

| 事件 | 处理 |
|---|---|
| `message` | 追加 `answer` 增量到当前回复文本 |
| `message_end` | 收尾：读取 `metadata.usage`，标记消息完成，流结束 |
| `ping` | 心跳，忽略 |
| `error` | 展示错误态（`status` / `code` / `message`） |
| （内部事件 `thinking_*` / `tool_call_*` / `gate_checked` / `artifact_ready` 等由后端以 `message` 帧正文聚合输出，前端**不直接消费**；前端消费的是对外判别帧 `message` / `message_end` / `ping` / `error`） |

> ⚠️ 契约澄清：对外 SSE 判别帧仅 `message` / `message_end` / `ping` / `error` 四种。思考/工具/产物是后端在 `message` 帧正文中以文本形式呈现的，前端**渲染正文即可**；若正文中不含结构化标记，则 M2–M4 依赖后端正文输出中的可识别片段。实现前需与后端确认正文是否携带结构化片段（如特殊标记 / JSON 块），据此决定 M2–M4 为「解析正文」还是「保持纯正文展示」。

## 4. 环境变量（`.env.example`，提交模板）

| 变量 | 默认 | 说明 |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | 后端 base URL |
| `VITE_SSE_TIMEOUT_MS` | `300000` | 流式请求整体超时 |
| `VITE_CHAT_QUERY_MAX` | `4000` | 前端 query 长度上限（对齐后端） |
| `VITE_FEATURE_THINKING` | `true` | 思考块展示开关 |
| `VITE_FEATURE_TOOL_CALLS` | `true` | 工具调用卡展示开关 |
| `VITE_FEATURE_ARTIFACTS` | `true` | 产物链接展示开关 |

## 5. 验收标准（v1）

1. 首条消息自动创建会话，`X-Conversation-Id` 正确解析，续聊复用同一会话。
2. 流式回复逐字追加，`message_end` 后消息完成、用量可见；无残留 loading。
3. 停止生成后状态干净，可继续发新消息或重试。
4. Markdown 代码块高亮正确；含 `javascript:` 链接 / `<script>` 的恶意正文被清洗（不执行、不弹出）。
5. 刷新页面后会话列表保留；切换/删除会话行为正确。
6. 后端不可用 / 4xx / SSE error 帧 → 均展示可读错误文案，不白屏。
7. `pnpm vue-tsc --noEmit`、`pnpm lint` 零错误；自检清单全过。

## 6. 风险与依赖

* **依赖后端正文结构**：M2–M4 高级事件展示依赖后端在正文中输出可识别片段（见 §3 契约澄清），需先确认。
* **无历史接口**：会话历史不在前端本地则刷新后只留元数据，消息区为空 —— 属已知限制，不阻塞 v1。
