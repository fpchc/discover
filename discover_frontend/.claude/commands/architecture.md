# 前端总体架构（Vite + React 19 SPA）

## 适用场景 / 何时触发

- 需要理解整体分层、目录边界、模块依赖方向时
- 新增文件、调整目录结构、判断某段逻辑该放哪一层时
- 生成项目骨架前的第一份必读规范
- 判断某项能力属于「组件」「hooks」「store」还是「lib 纯逻辑」时

> 全局红线约束在 `CLAUDE.md`，不重复。性能与状态粒度红线见 `performance.md`。
> 架构快照与模块路径映射见 `.ai/ARCHITECTURE.md`、`.ai/MODULE_MAP.md`（结构变化后同步更新）。

---

## 1. 项目定位

ChatGPT 风格单页对话应用。账号体系（手机号+密码登录，JWT 认证，数据按账号隔离，见 `ACCOUNT_API.md`）。
后端为 `discover_backend`（多智能体承载平台）。

框架层采用 **Vite + React 19（纯客户端 SPA）**：Vite 承担构建 / dev server / 模块装配唯一入口，
渲染始终在浏览器端，静态产物输出 `dist/`，部署保持 nginx 静态托管。**纯客户端 SPA 为可判定硬约束**
（见 `CLAUDE.md` 第 1 节），不引入 SSR / 水合。

前端**只消费已有 API**（`POST /api/v1/chat-messages`、历史 `GET /conversations` 等、文件
`GET|POST /files/upload` 等，见 `.claude/feature/API.md`），不新增后端接口。会话列表 / 消息历史由
后端接口持有，前端不做会话数据本地持久化。

## 2. 分层与依赖方向

依赖严格自上而下，禁止反向引用。**lib/ 为纯逻辑层（叶子），禁止引用 React。**

```
src/
├── main.tsx                    入口：createRoot + 全局样式 + 主题初始化
├── App.tsx                     应用壳层 + 页面编排（侧栏 / 主区 / 输入区串联）
├── index.css                   Tailwind + 设计令牌（明暗双主题）+ 全局 markdown 样式
├── types.ts                    后端契约类型（映射 pydantic；禁止组件内散落重复定义）
├── env.ts                      环境配置唯一入口（VITE_* 类型化收窄，禁止组件直读 import.meta.env）
│
├── lib/                        纯逻辑层（叶子，无 React 依赖，可单测）
│   ├── api.ts                  axios 实例 + 对话/历史/文件/助手接口封装 + 认证（login / fetchMe / Bearer 拦截器 / 全局 401 回调，HTTP 唯一出口）
│   ├── auth.ts                 登录令牌持久化（localStorage `disf_auth_token` 读写，唯一事实源）
│   ├── errors.ts               错误映射（HTTP 状态码 + SSE error 帧 → 可读文案）
│   ├── history.ts              MessageRecord → ChatMessage 映射（纯函数）
│   ├── sse.ts                  SSE 帧解析原语（纯函数，data: 行 → 判别联合帧）
│   ├── stream.ts               流读取 + 帧分发（ReadableStream → 回调）
│   └── utils.ts                cn() 等工具（clsx + tailwind-merge）
│
├── hooks/                      React 生命周期相关可复用逻辑
│   ├── useChatStream.ts        对话发送 / 会话列表 / 历史加载编排（send/stop/retry/cancel/openConversation/loadList）
│   ├── useTheme.ts             明暗主题（system 跟随 / 切换 / localStorage 记忆，维护 html.dark）
│   ├── useFileUpload.ts        文件上传（本地校验 config / 上传 / 列表 / 预览 URL）
│   └── useNetworkStatus.ts     网络状态监听（online/offline）
│
├── stores/                     Zustand 单一事实源（跨组件共享状态唯一通道）
│   ├── chat.ts                 当前会话：activeMessages / conversationId / isStreaming / loadingHistory
│   ├── conversations.ts        会话列表（后端 GET /conversations 为唯一事实源）
│   ├── assistants.ts           助手目录 + 当前选择（agent_id）
│   └── auth.ts                 账号认证（status/account；resolveSession / login / logout / expire）
│
└── components/
    ├── ui/                     shadcn 拷入组件（button / dropdown-menu / input / skeleton / sonner 触发器等）
    ├── AuthGate.tsx            认证闸门（loading → 登录页 → 主界面；main.tsx 包裹层）
    ├── LoginScreen.tsx         登录页（手机号 + 密码 → POST /auth/login 得 JWT）
    ├── Sidebar.tsx             侧栏（品牌区 / 新对话 / 技能与助手 / 最近对话 / 底部账号区 + 退出）
    ├── ChatWindow.tsx          对话主区（头部 / 空态 / 消息流 / 滚动）
    ├── ChatInput.tsx           输入框（textarea / 附件 / 助手胶囊 / 发送/停止）
    ├── AssistantMenu.tsx       助手选择下拉（通用 + 专家）
    ├── MessageBubble.tsx       消息气泡（React.memo；思考分区 / markdown / 复制 / 重试）
    └── Markdown.tsx            react-markdown 渲染组件（remark-gfm / rehype-highlight）

根级（src/ 之外）
├── index.html                  入口 HTML（theme-init.js / lang=zh-CN / 标题）
├── vite.config.ts              Vite 配置：envDir ./env、server.proxy（读 VITE_PROXY_TARGET）、outDir dist
├── tsconfig.json               TS strict 配置
├── vitest.config.ts            单测配置
├── public/theme-init.js        首屏防主题闪白（CSP 兼容经典脚本）
├── env/                        环境模板（VITE_*，envDir 直接注入）
├── Dockerfile / nginx.conf / security-headers.conf
└── 根配置                       package.json / biome.json / .github
```

> 环境文件统一收容于 `env/`，Vite 原生支持 `envDir`（与旧 Nuxt 不同，无需 `--dotenv` 注入）；
> `VITE_*` 自动流入 `import.meta.env`，统一在 `src/env.ts` 收窄。`Dockerfile` / `nginx.conf`
> 在本项目根，全栈 compose 在仓库根。

**结构性红线**：组件不直接发 HTTP、不直接解析 SSE、不持有对话副本；HTTP 唯一出口在 `src/lib/api.ts`；
SSE 解析唯一处在 `src/lib/sse.ts` + `src/lib/stream.ts`；共享状态唯一通道是 Zustand
（`src/stores/`）；纯逻辑一律进 `src/lib/`（禁止在组件 / hooks 内嵌可纯化的逻辑）。

## 3. 目录职责

| 路径 | 职责 |
|---|---|
| `CLAUDE.md` | 全局红线约束 |
| `.claude/feature/` | 需求 / API 契约（只读参考，见 CLAUDE.md 第 12 节） |
| `.claude/commands/*.md` | 单项职责规范：`architecture.md`（结构）、`performance.md`（性能红线） |
| `.ai/*.md` | 架构快照 + 模块路径映射（结构变化后同步更新） |
| `src/main.tsx` | 应用入口（React 19 `createRoot` + 全局样式 + 主题初始化 + 注册全局 401 回调 + AuthGate 包裹） |
| `src/App.tsx` | 应用壳层 + 页面编排（单页无路由；订阅账号展示 / 退出） |
| `src/index.css` | Tailwind + 设计令牌 + markdown 全局样式 |
| `src/types.ts` | 后端契约类型（映射 pydantic；含账号认证 AccountRecord / LoginResponse） |
| `src/env.ts` | 环境配置唯一入口（`VITE_*` 类型化收窄） |
| `src/lib/` | 纯逻辑（api / auth / errors / history / sse / stream / utils），无 React 依赖 |
| `src/hooks/` | React 生命周期相关逻辑（useChatStream / useTheme / useFileUpload / useNetworkStatus） |
| `src/stores/` | Zustand store（chat / conversations / assistants / auth） |
| `src/components/ui/` | shadcn 拷入组件（button / dropdown-menu / input / skeleton 等） |
| `src/components/` | 认证与域组件（AuthGate / LoginScreen / Sidebar / ChatWindow / ChatInput / AssistantMenu / MessageBubble / Markdown） |

## 4. 模块职责与边界

| 模块 | 负责 | 不负责 |
|---|---|---|
| `src/App.tsx` | 页面编排、会话与消息渲染的串联、全局快捷键 | 不发 HTTP、不解析 SSE |
| `src/components/MessageBubble.tsx` | 按 props 渲染消息 / 思考 / markdown / 复制 / 重试（`React.memo`） | 不改 store、不持有对话副本、流式不重解析（见 performance.md） |
| `src/components/ChatInput.tsx` | 输入框 / 附件 / 助手胶囊 / 发送/停止（纯展示 + 事件上报） | 不发 HTTP、不直接改 store |
| `src/hooks/useChatStream.ts` | 发送编排 + 列表 / 历史加载、`AbortController` 取消 + 卸载清理 | 不做 UI 渲染、不碰 DOM |
| `src/stores/chat.ts` | 消息追加、流式状态、取消复位、思考分区（单一事实源） | 不做 HTTP / SSE 读取 |
| `src/stores/conversations.ts` | 会话列表状态（后端为唯一事实源） | 不做 HTTP / 不持久化 |
| `src/stores/auth.ts` | 登录态（status / account）、resolveSession / login / logout / expire、登出重置三 store 防跨账号泄漏 | 不做 UI 渲染 |
| `src/lib/api.ts` | 对话 / 历史 / 文件 / 助手请求封装 + 认证（login / fetchMe / Bearer 拦截器 / 全局 401 回调）+ 错误映射 | 不被组件绕开裸 `fetch` |
| `src/lib/auth.ts` | 令牌持久化（localStorage `disf_auth_token` 读写） | 不包含账号业务状态 |
| `src/lib/sse.ts` | 帧解析原语（纯函数） | 不包含对话业务状态 |
| `src/lib/stream.ts` | 流读取 + 帧分发（消费层） | 不包含对话业务状态 |
| `src/lib/history.ts` | MessageRecord → ChatMessage 映射（纯函数） | 不包含对话业务状态 |
| `src/lib/errors.ts` | HTTP + SSE 错误 → 可读文案（统一收敛） | 不包含 UI 状态 |

## 5. 关键结构性决策

| 决策 | 选型 | 理由 |
|---|---|---|
| 框架层 | Vite + React 19（纯客户端 SPA） | 构建 / dev 唯一入口；静态产物 `dist/`；nginx 托管不变 |
| 样式 | Tailwind CSS 4（`@theme`，CSS-first） | 设计令牌全走 CSS 变量，组件零定制成本 |
| 组件原语 | shadcn/ui（Radix + Tailwind，拷入 `src/components/ui/`） | 样式归本项目、a11y 由 Radix 兜底 |
| 状态共享 | Zustand（`src/stores/`） | 粒度订阅；activeMessages 与历史列表解耦 |
| SSE 传输 | `fetch` + `ReadableStream` | POST 语义无法用 `EventSource`，解析集中在 `lib/sse.ts` |
| Markdown 渲染 | react-markdown + remark-gfm + rehype-highlight | 默认不渲染原始 HTML（安全收敛） |
| 会话历史数据源 | 后端历史接口（`GET /conversations` 等） | 后端回合粒度持有，前端不持久化 |
| 路由 | 无（单页） | 侧栏切换是状态不是路由；将来多页再加 react-router |
| HTTP 出口 | `src/lib/api.ts` 统一实例 | 错误映射 / 契约集中一处 |

## 6. 结构性改动自检要点

- [ ] 新增文件落位符合「分层与依赖方向」，无反向引用（`lib/` 不引用 React）
- [ ] 共享状态经 Zustand，未新增组件间互引
- [ ] HTTP / SSE 未在 `src/lib/api.ts`、`src/lib/sse.ts` + `stream.ts` 之外重复实现
- [ ] 纯逻辑未散落在组件 / hooks 内
- [ ] 未引入 `tailwind.config.js`（Tailwind v4 全 CSS 配置）
- [ ] 目录职责表（本文件 §3）已随结构变化更新
- [ ] 结构变化已同步 `.ai/ARCHITECTURE.md` 与 `.ai/MODULE_MAP.md`
