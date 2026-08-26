# 前端总体架构

## 适用场景 / 何时触发

- 需要理解整体分层、目录边界、模块依赖方向时
- 新增文件、调整目录结构、判断某段逻辑该放哪一层时
- 生成项目骨架前的第一份必读规范
- 判断某项能力属于「组件」「composable」「store」还是「api 封装」时

> 全局红线约束在 `CLAUDE.md`，不重复。本文件只讲结构：代码放哪里、依赖方向、模块边界。
> 架构快照与模块路径映射见 `.ai/ARCHITECTURE.md`、`.ai/MODULE_MAP.md`（结构变化后同步更新）。

---

## 1. 项目定位

单页对话应用，模仿 ChatGPT 页面。单用户、无鉴权演示。后端为 `discover_backend`（多智能体承载平台）。

前端**只消费已有 API**（`POST /api/v1/chat-messages`、历史 `GET /conversations` 等、文件 `GET|POST /files/upload` 等，见 `.claude/feature/API.md`），不新增后端接口。会话列表 / 消息历史由后端接口持有，前端不做会话数据本地持久化。

## 2. 分层与依赖方向

依赖严格自上而下，禁止反向引用。

```
src/
├── views/             视图层：页面编排（ChatView.vue，路由占位）
├── components/        组件层：纯展示 + emits 上报，不持有对话副本
│   ├── layout/        页面骨架：AppSidebar（会话列表）、ChatWindow
│   ├── chat/          对话部件：MessageBubble / MarkdownRenderer / ThinkingBlock /
│   │                  ToolCallCard / ArtifactLink / ChatInput
│   └── common/        通用无状态组件
├── config/            环境配置唯一入口（env.ts 类型化收窄，禁止组件直读 import.meta.env）
├── composables/       组合层：可复用逻辑（唯一实现点）
│   ├── useChatStream  对话发送 / 会话列表 / 历史加载编排（send/stop/retry/cancel/openConversation/loadList）
│   ├── useMarkdown    Markdown 渲染 + DOMPurify 清洗
│   ├── useNetworkStatus  网络状态监听（online/offline）
│   └── useFileUpload  文件上传（本地校验 config / 上传 / 列表 / 预览 URL）
├── stores/            状态层：Pinia 单一事实源
│   ├── conversations  会话列表（后端 GET /conversations 为唯一事实源，纯状态变更）
│   └── chat           消息 / 流式状态 / 用量汇总
├── api/               数据层：HTTP 唯一出口
│   ├── client.ts      axios 实例（blocking / 历史 / 文件）
│   ├── chat.ts        SSE 对话请求（fetch）
│   ├── history.ts     历史接口（conversations / messages / usage）
│   ├── files.ts       文件接口（upload 配置 / 上传 / preview URL）
│   ├── errors.ts      错误映射（HTTP + SSE error 帧）
│   └── types.ts       后端契约类型（映射 pydantic）
├── styles/            全局样式与 Element Plus 主题变量
└── utils/             纯工具（叶子层）：sse.ts 帧解析原语、history.ts 消息映射（MessageRecord→ChatMessage）、logger.ts 结构化日志
```

> 环境文件统一收容于 `env/`（vite `envDir: ./env`），dev/test/prod 三套模板；`Dockerfile` / `nginx.conf` 等构建文件在本项目根，全栈 compose 在仓库根。

**结构性红线**：组件不直接发 HTTP、不直接解析 SSE、不持有对话副本；HTTP 唯一出口在 `src/api/`；SSE 解析唯一处在 `useChatStream.ts`；共享状态唯一通道是 Pinia。

## 3. 目录职责

| 路径 | 职责 |
|---|---|
| `CLAUDE.md` | 全局红线约束 |
| `docs/REQUIREMENTS.md` | 详细需求：功能点、交互、SSE 事件表、验收标准 |
| `.claude/commands/*.md` | 单项职责规范，一文件一职责，LLM 按任务内容自行识别加载 |
| `.claude/feature/` | 历史需求参考，只读，见 CLAUDE.md「禁止扫描 / 读取路径」 |
| `.ai/*.md` | 架构快照 + 模块路径映射（结构变化后同步更新） |
| `src/api/` | HTTP 唯一出口：`client.ts`（axios 实例）、`chat.ts`、`history.ts`、`files.ts`、`types.ts`（后端契约类型） |
| `src/stores/` | Pinia store：`conversations.ts`（会话列表，后端为事实源）、`chat.ts`（消息 / 流式状态 / 用量） |
| `src/composables/` | 可复用逻辑：`useChatStream.ts`（发送 / 历史编排）、`useMarkdown.ts`（渲染 + 清洗）、`useFileUpload.ts`（文件上传） |
| `src/components/layout/` | 页面骨架：`AppSidebar.vue`（会话列表）、`ChatWindow.vue` |
| `src/components/chat/` | 对话部件：`MessageBubble` / `MarkdownRenderer` / `ThinkingBlock` / `ToolCallCard` / `ArtifactLink` / `ChatInput`（含文件上传） |
| `src/components/common/` | 通用无状态组件 |
| `src/views/` | 路由页面（`ChatView.vue`） |
| `src/styles/` | 全局样式与 Element Plus 主题变量 |
| `src/utils/` | 纯工具（`sse.ts` 帧解析原语、`history.ts` 消息映射、`logger.ts` 结构化日志） |

## 4. 模块职责与边界

| 模块 | 负责 | 不负责 |
|---|---|---|
| `views/ChatView.vue` | 页面编排、会话与消息渲染的串联 | 不发 HTTP、不解析 SSE；编排页超 300 行需 `// pragma: 简化 — 编排页` |
| `components/chat/*` | 按 props 渲染消息 / 思考 / 工具卡 / 产物链接 / 输入框，emits 上报 | 不直接改 store、不持有对话副本、不拦截协议细节 |
| `composables/useChatStream` | 发送编排 + 会话列表加载 / 历史加载（`openConversation` / `loadList`）、`AbortController` 取消 | 不做 UI 渲染、不碰 DOM |
| `composables/useMarkdown` | markdown-it 渲染 + DOMPurify 清洗 | 不把未清洗 HTML 交给 `v-html` |
| `composables/useFileUpload` | 上传配置校验 / 上传 / 文件列表 / 预览 URL | 不直接改 store、不做消息发送 |
| `stores/chat` | 消息追加、流式状态、用量汇总、取消复位（单一事实源） | 不做 HTTP 调用 |
| `stores/conversations` | 会话列表状态（后端 `GET /conversations` 为唯一事实源） | 不做 HTTP / 不持久化 |
| `api/chat.ts` | 对话请求封装、错误映射 | 不被组件绕开裸 `fetch` |
| `api/history.ts` | 历史接口（列表 / 消息流 / 用量） | 不含业务状态 |
| `api/files.ts` | 文件接口（上传配置 / 上传 / 预览 URL） | 不含业务状态 |
| `api/types.ts` | 后端契约类型 | 定义不散落在组件内 |
| `utils/sse.ts` | 帧解析原语（纯函数） | 不包含对话业务状态 |
| `utils/history.ts` | MessageRecord → ChatMessage 映射（纯函数） | 不包含对话业务状态 |

## 5. 关键结构性决策

| 决策 | 选型 | 理由 |
|---|---|---|
| 状态共享 | Pinia store | 单一事实源；流式增量只写 store，组件只渲染 |
| SSE 传输 | `fetch` + `ReadableStream` | POST 语义无法用 `EventSource`，解析集中在 composable |
| Markdown 渲染 | markdown-it + DOMPurify | 模型输出 HTML 必须清洗（安全红线） |
| 会话历史数据源 | 后端历史接口（`GET /conversations`、`GET /conversations/{id}/messages`） | 后端回合粒度持有，前端不持久化；删除为前端本地移除 |
| HTTP 出口 | `src/api/` 统一实例 | 错误映射 / 契约集中一处 |
| 路由 | Vue Router 4 | 预留；当前仅一屏对话 |

## 6. 结构性改动自检要点

- [ ] 新增文件落位符合「分层与依赖方向」，无反向引用
- [ ] 共享状态经 Pinia，未新增组件间互引
- [ ] HTTP / SSE 未在 `src/api/` 与 `useChatStream.ts` 之外重复实现
- [ ] 目录职责表（本文件 §3）已随结构变化更新
- [ ] 结构变化已同步 `.ai/ARCHITECTURE.md` 与 `.ai/MODULE_MAP.md`
