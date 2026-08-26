# 架构快照

> 模型记忆：反映**当前**代码结构，与 `.claude/commands/architecture.md`（规范）互补。
> 结构变化后必须同步更新（见 `CLAUDE.md` 第 9 节）。

## 当前结构（2026-08-26 Nuxt 4 迁移落地）

```
discover_frontend/
├── nuxt.config.ts            Nuxt 装配：ssr:false、nitro.devProxy（读 VITE_PROXY_TARGET）、modules（@pinia/nuxt、@element-plus/nuxt）、全局 CSS、app.head
├── env/                      环境模板（脚本 --dotenv 加载）：.env.example / .development / .test / .production
├── app/                      客户端代码（Nuxt 4 srcDir）
│   ├── app.vue               应用壳层（NuxtPage）
│   ├── pages/index.vue       对话页（文件路由，底层 vue-router）
│   ├── components/
│   │   ├── layout/           AppSidebar / ChatWindow（空态 + 光晕 + 主题切换）
│   │   ├── chat/             AssistantPicker（助手选择）/ ChatInput / MessageBubble（头像 + 渐变气泡 + 思考卡）
│   │   └── common/           AppIcon（手写内联 SVG，无图标依赖）
│   ├── composables/          useChatStream / useMarkdown / useFileUpload / useNetworkStatus / useTheme
│   ├── stores/               assistants / chat / conversations
│   ├── api/                  client / chat / history / files / assistants / types / errors
│   ├── utils/                sse / history / logger
│   ├── config/env.ts         环境配置唯一入口（类型化 VITE_*，禁止直读 import.meta.env）
│   ├── styles/               theme.css（双主题令牌）/ main.css（全局 + Markdown 正文）
│   ├── plugins/globalErrorHandler.ts  全局错误边界（客户端插件）
│   └── env.d.ts              VITE_* 类型声明
├── public/theme-init.js      首屏防主题闪白（CSP 兼容经典脚本，读取 disf_theme）
└── 根配置                    package.json / vitest.config.ts / tsconfig.json（extends .nuxt）/ biome.json
```

## 关键设计决策

| 决策 | 选型 | 理由 |
|---|---|---|
| 框架层 | **Nuxt 4（SPA 模式，`ssr: false` 固定）** | 构建 / dev / 文件路由 / 模块装配唯一入口；渲染在浏览器端，部署保持 nginx 静态托管（产物 `.output/public`） |
| 状态共享 | Pinia store（`@pinia/nuxt`） | 单一事实源；流式增量只写 store，组件只渲染 |
| SSE | fetch + ReadableStream | POST 语义；解析原语在 `utils/sse.ts`，读取在 `composables/useChatStream.ts` |
| 流式编排 | `useChatStream` composable 驱动 store | store 只做状态与变更，HTTP/SSE/取消/超时/retry 全在编排层；turn token 作废旧流防幽灵增量 |
| Markdown | markdown-it + highlight.js + DOMPurify | 安全红线：渲染结果必须 sanitize |
| 错误映射 | `api/errors.ts` 集中维护 | HTTP 状态码 + SSE error 帧 → 可读文案一处收口 |
| 显式助手选择 | `GET /assistants` 目录 + 请求体 `agent_id` + `message_end`/blocking `metadata.assistant` 回显 | 模型不再自动路由（`select_agent`/`select_skill` 已移除）；用户显式选专家 / 通用对话，选择随下一次发送生效（API.md §6） |
| 历史数据源 | 后端历史接口（`GET /conversations`、`/conversations/{id}/messages`、`/conversations/{id}/usage`，见 `.claude/feature/API.md`） | 会话列表 / 消息 / 用量以后端为唯一事实源，前端不持久化；新会话乐观入列，回合结束后 `loadList` 校准 |
| 文件上传 | `useFileUpload` composable + ChatInput 附件（`GET|POST /files/upload`、`GET /files/{id}/preview`） | 上传前本地校验扩展名 / 大小；图片内联缩略、其余新窗口 / `a[download]` |
| 环境 | VITE_* 收容 `env/`，经脚本 `--dotenv ./env/.env.{development,test,production}` 注入 process.env 流入 `import.meta.env` | Nuxt 不采纳 `vite.envDir`；配置驱动、无硬编码、无密钥模板提交 |
| 视觉体系 | 品牌渐变（靛蓝→紫→淡紫）+ 明暗双主题（`useTheme` 维护 `html.dark`，记忆 `disf_theme`）+ 空态建议卡片 + 光晕动效 | 仿主流 AI 产品观感；EP 变量映射到主题令牌；`theme-init.js` 首屏防闪白 |
| 代码块 | highlight.js 统一 `github-dark`，`pre.codeblock` 深色外壳 + `::before` 语言标签 | 明暗主题一致；markdown-it highlight 返回以 `<pre` 开头避免二次包裹 |
| 校验 | Biome（Rust，lint+format 单一源）+ `nuxt typecheck`（vue-tsc） | 类型检查基线；lint 排除 `.nuxt/`、`.output/` |
| 部署 | 多阶段 Docker + nginx（静态托管 `.output/public`，`/api` 反代 SSE 优化） | 同源 SSE 反代、hash 长缓存、CSP；`Dockerfile` / `nginx.conf` 在项目根，全栈 compose 在仓库根 |

## 关键契约确认（2026-08-24，与后端对齐）

* **SSE 判别帧共 7 种**：`message` / `message_end` / `ping` / `error` + 思考三帧
  `thinking_started` / `thinking_delta` / `thinking_ended`（`routes_chat.py:_stream_sse` 映射）。
* **思考已对外**：`thinking_*` 帧携带思考过程（`thinking_delta.content` 增量、`thinking_ended.duration_ms`），
  前端渲染为可折叠思考分区（ThinkingBlock），由 `VITE_FEATURE_THINKING` 开关控制显示。工具走 `tool_call_*`、
  产物走 `artifact_ready` 仍为后端**内部**事件，不进入对外正文；ToolCallCard / ArtifactLink 保持不在 v1。
* **HTTP 错误体**：PlatformError `{error:{category,message}}` / FastAPI `{detail}`。
* **SSE 帧 `created_at` 为 epoch 秒**；历史接口记录 `created_at` 为 ISO 8601（pydantic 序列化）。
* **`message_end.metadata.usage` = 5 键**：`{prompt_tokens, completion_tokens, total_tokens, cached_read_tokens, cached_write_tokens}`（API.md §3）。
* **历史 / 文件接口**（API.md §1 / §2）：会话列表、消息流、用量汇总由后端提供；产物下载接口
  `/sessions/{sid}/artifacts/{aid}` 已移除，预览 / 下载改走 `GET /api/v1/files/{file_id}/preview`（§3 / §4）。
* **助手选择**（API.md §6）：`GET /assistants` 返回 `{id,type,name,description,capabilities}`（expert + generic，
  generic 为保留字）；请求体可选 `agent_id`（首轮绑定 / 续聊沿用 / `"generic"` 切回通用 / 未知 id → 404）；
  `message_end` 与 blocking 的 `metadata.assistant` 回显当前回合生效助手
  （`{"type":"expert","id":"discover"}` / `{"type":"generic","id":null}` / 缺失 = 新会话未绑定）。
  `select_agent` / `select_skill` 已移除，模型不再决定进哪个助手。

## 已知限制

- **Biome 对 Vue**：暂不识别 `<script setup>` 模板绑定，故 `biome.json` 对 `.vue` 关闭
  `noUnusedVariables` / `noUnusedImports`（避免误删模板引用变量）；TS 文件仍启用。
- `@element-plus/nuxt` 的 Vite `optimizeDeps.include` 需 `dayjs` / `lodash-unified` 可解析，
  故作为 devDependencies 直装（避免 pnpm 严格隔离下 dev 警告）。
- `@element-plus/icons-vue` 不引入（AppIcon 手写 SVG，CLAUDE.md 第 1 节硬约束）。
- 本机开发若配置了系统代理（`HTTP_PROXY`），访问 localhost 需经 `--noproxy` 或浏览器 `NO_PROXY`。

## 当前能力边界（v1 功能已落地）

对话全流程可用：发送（Enter/Shift+Enter、长度校验）、流式打字机、思考过程展示（`thinking_*` 帧 →
可折叠思考分区，多段思考合并、结束后显示耗时）、会话自动创建与续聊
（`X-Conversation-Id` 优先 / 帧内 id 兜底）、停止生成（保留已收内容）、错误态与可读文案、
阻塞模式兜底重试、Markdown 渲染（sanitize + 高亮、代码块深色外壳）、复制、用量展示（单条 + 会话级汇总角标）、
会话侧边栏（新建 / 切换 / 删除，列表来自后端 `GET /conversations`）、历史消息加载（`GET /conversations/{id}/messages` 映射渲染）、
文件上传（本地校验 → 上传 → 预览 / 下载 / 删除）、<768px 响应式抽屉。
历史数据源切换（2026-08-26）：会话列表与消息快照的 localStorage 持久化已移除，改由后端历史接口提供。

**显式助手选择（2026-08-26）**：聊天页头部「助手选择器」拉取 `GET /assistants` 目录，用户显式选专家 / 通用对话，
每次发消息带 `agent_id`（首轮绑定 / 续聊切换），回合结束按 `metadata.assistant` 回显选择器；
打开历史会话按 `ConversationRecord.agent_id` 对齐选择器；旧「多智能体自动路由」文案与徽标已移除。

**框架迁移（2026-08-26）**：由 Vue 3 + Vite 迁移至 **Nuxt 4（SPA `ssr:false`）**——`app/` 目录结构、
文件路由、`@pinia/nuxt` + `@element-plus/nuxt` 模块装配、`nuxt typecheck` 类型检查基线、
`nuxt generate` 静态产物（`.output/public`）nginx 托管；业务代码（components/composables/stores/api/utils）逻辑零改动。

**视觉重构（2026-08-25）**：页面按主流 AI 产品观感重写——明暗双主题 + 一键切换（默认跟随系统、
记忆偏好、首屏防闪白）、品牌渐变（靛蓝→紫→淡紫，去高饱和粉）、空态欢迎区（大标题 + 4 张建议
卡片点击即发送 + 光晕漂移动画）、玻璃输入卡 + 圆形渐变发送钮、助手渐变头像 / 用户渐变气泡 /
思考卡 shimmer、桌面侧栏折叠；功能与数据流零改动。

**不在 v1**：ToolCallCard / ArtifactLink 高级事件卡片——工具 / 产物事件仍为后端内部事件，不进入
对外正文（见关键契约确认）；若后端后续开放，再按 feature 开关接入。
