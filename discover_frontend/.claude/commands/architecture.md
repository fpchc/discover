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

前端**只消费已有 API**（`POST /api/v1/chat-messages`），不新增后端接口。会话历史由后端持有，前端仅本地持久化会话元数据。

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
│   ├── useChatStream  SSE 流读取（ReadableStream → 判别联合帧）
│   ├── useMarkdown    Markdown 渲染 + DOMPurify 清洗
│   └── useNetworkStatus  网络状态监听（online/offline）
├── stores/            状态层：Pinia 单一事实源
│   ├── conversations  会话列表 + 本地持久化
│   └── chat           消息 / 流式状态
├── api/               数据层：HTTP 唯一出口
│   ├── client.ts      axios 实例（blocking）
│   ├── chat.ts        SSE 对话请求（fetch）
│   ├── errors.ts      错误映射（HTTP + SSE error 帧）
│   └── types.ts       后端契约类型（映射 pydantic）
├── styles/            全局样式与 Element Plus 主题变量
└── utils/             纯工具（叶子层）：sse.ts 帧解析原语、persist.ts localStorage 封装、logger.ts 结构化日志
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
| `src/api/` | HTTP 唯一出口：`client.ts`（axios 实例）、`chat.ts`、`types.ts`（后端契约类型） |
| `src/stores/` | Pinia store：`conversations.ts`（会话列表 + 本地持久化）、`chat.ts`（消息 / 流式状态） |
| `src/composables/` | 可复用逻辑：`useChatStream.ts`（SSE 解析与取消）、`useMarkdown.ts`（渲染 + 清洗） |
| `src/components/layout/` | 页面骨架：`AppSidebar.vue`（会话列表）、`ChatWindow.vue` |
| `src/components/chat/` | 对话部件：`MessageBubble` / `MarkdownRenderer` / `ThinkingBlock` / `ToolCallCard` / `ArtifactLink` / `ChatInput` |
| `src/components/common/` | 通用无状态组件 |
| `src/views/` | 路由页面（`ChatView.vue`） |
| `src/styles/` | 全局样式与 Element Plus 主题变量 |
| `src/utils/` | 纯工具（`sse.ts` 帧解析原语、`persist.ts` localStorage 封装） |

## 4. 模块职责与边界

| 模块 | 负责 | 不负责 |
|---|---|---|
| `views/ChatView.vue` | 页面编排、会话与消息渲染的串联 | 不发 HTTP、不解析 SSE；编排页超 300 行需 `// pragma: 简化 — 编排页` |
| `components/chat/*` | 按 props 渲染消息 / 思考 / 工具卡 / 产物链接 / 输入框，emits 上报 | 不直接改 store、不持有对话副本、不拦截协议细节 |
| `composables/useChatStream` | SSE 帧解析、事件分派、`AbortController` 取消 | 不做 UI 渲染、不碰 DOM |
| `composables/useMarkdown` | markdown-it 渲染 + DOMPurify 清洗 | 不把未清洗 HTML 交给 `v-html` |
| `stores/chat` | 消息追加、流式状态、取消复位（单一事实源） | 不做 HTTP 调用 |
| `stores/conversations` | 会话列表元数据 + localStorage（`disf_` 前缀） | 不存消息全文 |
| `api/chat.ts` | 对话请求封装、错误映射 | 不被组件绕开裸 `fetch` |
| `api/types.ts` | 后端契约类型 | 定义不散落在组件内 |
| `utils/sse.ts` | 帧解析原语（纯函数） | 不包含对话业务状态 |

## 5. 关键结构性决策

| 决策 | 选型 | 理由 |
|---|---|---|
| 状态共享 | Pinia store | 单一事实源；流式增量只写 store，组件只渲染 |
| SSE 传输 | `fetch` + `ReadableStream` | POST 语义无法用 `EventSource`，解析集中在 composable |
| Markdown 渲染 | markdown-it + DOMPurify | 模型输出 HTML 必须清洗（安全红线） |
| 会话持久化 | 仅元数据入 localStorage | 后端持有历史，前端不存全文 |
| HTTP 出口 | `src/api/` 统一实例 | 错误映射 / 契约集中一处 |
| 路由 | Vue Router 4 | 预留；当前仅一屏对话 |

## 6. 结构性改动自检要点

- [ ] 新增文件落位符合「分层与依赖方向」，无反向引用
- [ ] 共享状态经 Pinia，未新增组件间互引
- [ ] HTTP / SSE 未在 `src/api/` 与 `useChatStream.ts` 之外重复实现
- [ ] 目录职责表（本文件 §3）已随结构变化更新
- [ ] 结构变化已同步 `.ai/ARCHITECTURE.md` 与 `.ai/MODULE_MAP.md`
