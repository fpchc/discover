# 需求文档 — Discover Chat（React 重构版）

> 本文是前端**功能需求与验收标准**的唯一来源。后端接口契约见 `API.md`；结构分层见
> `.claude/commands/architecture.md`；性能/状态粒度红线见 `.claude/commands/performance.md`。
> 本目录（`.claude/feature/`）按 `CLAUDE.md` 第 12 节为只读参考，仅用户明确提及时才读取。

## 1. 产品定位

ChatGPT 风格的对话页，作为 `discover_backend`（多智能体承载平台）的前端。单用户、无鉴权演示。
页面目标是**好看、贴流行方向**：现代排版、品牌渐变 + 光效、流畅微交互、明暗双主题。

## 2. 页面结构

```
┌─────────────────────────────────────────────┐
│ 侧栏（可折叠 / 移动端抽屉）        │ 对话主区   │
│ ┌─────────────────────┐           │ ┌───────┐ │
│ │ 品牌区 Discover      │           │ │ 头部   │ │
│ │ 新对话 [Ctrl K]      │           │ │ 标题栏 │ │
│ │ 技能与助手（专家列表）│           │ ├───────┤ │
│ │ 最近对话（会话列表）  │           │ │ 消息流 │ │
│ │ 底部 主题切换/环境徽标│           │ ├───────┤ │
│ └─────────────────────┘           │ │ 输入区 │ │
│                                   │ └───────┘ │
└─────────────────────────────────────────────┘
```

- 桌面（≥768px）：侧栏 260px，可折叠（折叠后主区头部显示展开钮）。
- 移动（<768px）：侧栏变抽屉（`translateX` 滑出），配遮罩，头部汉堡钮打开。

## 3. 功能需求

### 3.1 对话发送（核心）

- 输入框：多行 textarea，Enter 发送、Shift+Enter 换行、合成输入（IME）中 Enter 不发送。
- 字数上限 `VITE_CHAT_QUERY_MAX`（默认 4000），超限 `sonner.warning` 提示，不发送。
- 发送后追加用户气泡 + 空助手气泡（流式态），输入框清空、进入 `streaming`。
- 流式期间发送钮变为「停止」钮；点击停止 = `AbortController.abort()`，**保留已收正文**，
  空内容则移除该半条消息（不留空气泡）。
- 失败/重试：消息错误态显示文案 + 「重试」钮；重试移除上一条失败助手消息，重开一条流式消息。
  重试优先走 `blocking` 兜底（`VITE_FEATURE_BLOCKING_FALLBACK` 开关），成功后按完整回复渲染。
- 流式异常（未到 `message_end` 即断）：提示重试并**保留已收内容**。
- 整体超时 `VITE_SSE_TIMEOUT_MS`（默认 15 分钟）→ `AbortController` 触发，显示超时文案。

### 3.2 思考分区

- `thinking_started` 打开思考分区；`thinking_delta` 增量追加；`thinking_ended` 收起并显示耗时。
- 思考可多段（思考→工具→再思考），全部追加同一分区，首个 start 打开、末次 end 收起。
- 思考进行中分区强制展开（顶部带 shimmer）；结束后可点击折叠/展开，展示 `已思考 N 秒`。
- 思考**不进正文**；`blocking` 模式无思考帧（后端不返回）。

### 3.3 助手选择

- 输入区胶囊选择器：显示当前助手名；点击弹出下拉（通用对话 + 专家目录）。
- 通用对话为保留项（id=`generic`），目录外固定渲染，描述「日常问答与随手提问」。
- 目录来自 `GET /assistants`（专家：`id/type/name/description/capabilities`）。
- 选中项随下一次 `/chat-messages` 生效（`agent_id` 显式绑定）；目录未加载时发送不带 `agent_id`。
- 回合结束回显：`message_end.metadata.assistant` → 同步选择器（缺失 = 新会话未绑定，保持现状）。
- 打开历史会话：以会话绑定助手（`ConversationRecord.agent_id`）校准选择器；未绑定 → 通用。
- 新建会话：选择器回落到通用对话。

### 3.4 文件上传（受 `VITE_FEATURE_FILES` 开关）

- 上传前 `GET /files/upload` 拉限制，本地校验扩展名 + 大小，失败 `sonner.warning`。
- 成功后文件进入输入框上方列表（缩略图/图标 + 名称 + 大小），支持预览（新窗口）与下载
  （`a[download]` 指向 `/files/{id}/preview`）。
- 单个文件逐个上传，上传中禁用附件钮；失败 `sonner.error`（走统一错误映射）。
- 文件不挂到对话消息（后端 `files` 字段暂不处理）。

### 3.5 会话历史

- 侧栏「最近对话」列表来自 `GET /conversations`（唯一事实源），按 `updated_at` 倒序，
  显示 `对话数 · HH:mm`（当天）或 `对话数 · M/D`。
- 加载中显示骨架屏；空列表显示空态文案。
- 点击会话 → `GET /conversations/{id}/messages` 拉历史，渲染用户+助手气泡（query+answer 同行）。
  切换会话前先 `abort()` 作废旧流（turn 作废防幽灵增量）。
- 新对话：首次发送后乐观入列（标题取首条 query 截断 `VITE_CONVERSATION_TITLE_MAX`），
  回合结束后用后端权威列表静默校准。
- 删除：调 `DELETE /conversations/{id}`；`204`/`404` 均按已删除处理并本地移除，其余错误保留条目。
  删除当前会话后清空消息区、选择器回落通用。

### 3.6 明暗主题

- 三态偏好：`light` / `dark` / `system`（默认跟随系统），记忆于 `localStorage['disf_theme']`。
- 底部切换钮：单键在明暗间翻转（system 态先落到当前实际值再翻转，结果写为显式偏好）。
- 首屏防 FOUC：`index.html` 内经典脚本同步执行（`public/theme-init.js`），CSP 兼容、非内联。
- `html.dark` class + `color-scheme` 由 `useTheme` 维护；组件只读 `isDark`，禁止直接改 class。

### 3.7 快捷键与健壮性

- `Ctrl/Cmd+K`：新建会话（与侧栏按钮提示一致）。
- 断网：顶部提示 / 暂停发送（`navigator.onLine` + online/offline 监听）。
- 环境徽标：非 production 在侧栏底部显示 `development` / `test`。

### 3.8 全局错误边界

- 捕获 `window.error` 与 `unhandledrejection`，统一结构化日志（`[discover][ERROR]` 前缀）。

## 4. SSE 事件表（后端契约，不可臆造）

| 事件 | 载荷 | 前端行为 |
|---|---|---|
| `message` | `{answer, created_at}` | 正文增量，追加当前助手消息 |
| `message_end` | `{metadata: {status, reason, limitations, unfinished_phases, usage, assistant?, phase?}, created_at}` | **流结束，无 `[DONE]`**；`status="cancelled"`（用户 stop）→ 停止语义（空内容移除 / 非空保留标记完成）；`phase="waiting_input"` → 阶段通知，以流关闭为回合真正结束 |
| `thinking_started` | `{created_at}` | 打开思考分区 |
| `thinking_delta` | `{content, created_at}` | 思考增量追加 |
| `thinking_ended` | `{duration_ms, created_at}` | 收起思考分区并显示耗时 |
| `ping` | — | 心跳，忽略 |
| `error` | `{status, code, message}`（code = ErrorCategory.value，status 经 http_status_for 映射） | 失败收尾（RunFailed），错误态 + 统一文案 |

所有帧（除 `ping`/`error`）带 `conversation_id`、`message_id`；会话 ID 以响应头
`X-Conversation-Id` 为优先，帧内 `conversation_id` 兜底。

高频运行事件（工具调用 / 进度 / Contract / 阶段切换 / LLMUsageUpdated）→ `map_run_event`
返回 None，不对前端逐条下发；`RunCancelled` → `message_end(status="cancelled")`，
`RunFailed` → `error` 帧，不落 `message_end`。

## 5. 性能要求（防坑点，见 performance.md 详细策略）

- [ ] 历史消息绝不随流式增量重渲（`MessageBubble` `React.memo`）
- [ ] 流式消息 Markdown 视图节流（30–50ms）+ `useDeferredValue`；高亮仅 `message_end` 后执行
- [ ] 侧栏等无关组件不订阅 `activeMessages`
- [ ] 卸载 / 切换会话时 `abort()`，无后台幽灵请求

## 6. 验收标准

- [ ] `pnpm typecheck` / `pnpm lint` / `pnpm test:run` 全绿
- [ ] 流式对话：正文逐字渲染、停止保留已收、超时/断线正确提示、重试可用
- [ ] 思考分区：多段思考正确累积、进行中展开带 shimmer、结束可折叠且显示耗时
- [ ] 助手选择：通用+专家渲染、选择随下次发送生效、历史会话绑定校准、回显同步
- [ ] 文件：本地校验、上传、预览、下载全链路可用（开关关闭时入口隐藏）
- [ ] 历史：列表/打开/删除/新会话乐观入列 + 静默校准
- [ ] 主题：三态切换、FOUC 无闪白、`localStorage` 记忆、system 跟随
- [ ] 移动端：抽屉侧栏 + 遮罩、头部汉堡；桌面折叠/展开正常
- [ ] 无未经清洗的 HTML 渲染（`dangerouslySetInnerHTML` 必经 DOMPurify）
