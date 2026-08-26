# 架构快照

> 模型记忆：反映**当前**代码结构，与 `.claude/commands/architecture.md`（规范）互补。
> 结构变化后必须同步更新（见 `CLAUDE.md` 第 9 节）。

## 当前结构（2026-08-24 骨架落地）

```
discover_frontend/
├── env/                        # 环境模板（vite envDir=./env）：.env.example / .development / .test / .production
├── .github/workflows/ci.yml    # CI 并行：lint / typecheck / test / build
├── src/
│   ├── main.ts                 入口：全局错误边界 + Pinia + Router + Element Plus（含 EP dark css-vars）
│   ├── App.vue                 壳层（RouterView）
│   ├── env.d.ts                VITE_* 类型声明
│   ├── config/env.ts           环境配置唯一入口（类型化收窄，禁止直读 import.meta.env）
│   ├── router/index.ts         路由（ChatView 懒加载）
│   ├── views/ChatView.vue      页面编排（桌面侧栏折叠 / 移动抽屉 / 空态建议透传）
│   ├── components/
│   │   ├── layout/             AppSidebar / ChatWindow（空态 + 光晕 + 主题切换）
│   │   ├── chat/               ChatInput / MessageBubble（头像 + 渐变气泡 + 思考卡）
│   │   └── common/             AppIcon（手写内联 SVG，无图标依赖）
│   ├── composables/            useChatStream / useMarkdown / useFileUpload / useNetworkStatus / useTheme
│   ├── stores/                 chat / conversations
│   ├── api/                    client / chat / history / files / types / errors
│   ├── utils/                  sse / history / logger
│   └── styles/                 theme.css（双主题令牌）/ main.css（全局 + Markdown 正文）
├── public/theme-init.js        首屏防主题闪白（CSP 兼容经典脚本，读取 disf_theme）
└── 根配置                      package.json / vite.config.ts / vitest.config.ts / tsconfig×3 / biome.json
```

## 关键设计决策

| 决策 | 选型 | 理由 |
|---|---|---|
| 状态共享 | Pinia store | 单一事实源；流式增量只写 store，组件只渲染 |
| SSE | fetch + ReadableStream | POST 语义；解析原语在 `utils/sse.ts`，读取在 `composables/useChatStream.ts` |
| 流式编排 | `useChatStream` composable 驱动 store | store 只做状态与变更，HTTP/SSE/取消/超时/retry 全在编排层；turn token 作废旧流防幽灵增量 |
| Markdown | markdown-it + highlight.js + DOMPurify | 安全红线：渲染结果必须 sanitize |
| 错误映射 | `api/errors.ts` 集中维护 | HTTP 状态码 + SSE error 帧 → 可读文案一处收口 |
| 历史数据源 | 后端历史接口（`GET /conversations`、`/conversations/{id}/messages`、`/conversations/{id}/usage`，见 `.claude/feature/API.md`） | 会话列表 / 消息 / 用量以后端为唯一事实源，前端不持久化；新会话乐观入列，回合结束后 `loadList` 校准 |
| 文件上传 | `useFileUpload` composable + ChatInput 附件（`GET|POST /files/upload`、`GET /files/{id}/preview`） | 上传前本地校验扩展名 / 大小；图片内联缩略、其余新窗口 / `a[download]`；后端暂不把文件挂到消息 |
| 环境 | VITE_* 收容 `env/`，`envDir: ./env` | 三环境模板、配置驱动、无硬编码 |
| 视觉体系 | 品牌渐变（靛蓝→紫→淡紫）+ 明暗双主题（`useTheme` 维护 `html.dark`，记忆 `disf_theme`）+ 空态建议卡片 + 光晕动效 | 仿主流 AI 产品观感；EP 变量映射到主题令牌保持一致；`theme-init.js` 首屏防闪白（生产 CSP 放行自托管经典脚本） |
| 代码块 | highlight.js 统一 `github-dark`，`pre.codeblock` 深色外壳 + `::before` 语言标签 | 明暗主题一致（GitHub/Vercel 风格）；markdown-it highlight 返回以 `<pre` 开头避免二次包裹 |
| 校验 | Biome（Rust，lint+format 单一源） | 替代 ESLint+Prettier，消除规则重叠 |
| 部署 | 多阶段 Docker + nginx（各子项目自带构建文件） | 同源 SSE 反代、hash 长缓存、CSP；`Dockerfile` / `nginx.conf` 在各自项目根，全栈 compose 在仓库根 |
| 会话持久化 | localStorage（`disf_` 前缀） | 仅元数据，不存消息全文 |

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

## 已知限制

- **Biome 对 Vue**：暂不识别 `<script setup>` 模板绑定，故 `biome.json` 对 `.vue` 关闭
  `noUnusedVariables` / `noUnusedImports`（避免误删模板引用变量）；TS 文件仍启用。
- Element Plus 全量引入（约 916 kB chunk），后续可切 `unplugin-vue-components` 按需引入。

## 当前能力边界（v1 功能已落地）

对话全流程可用：发送（Enter/Shift+Enter、长度校验）、流式打字机、思考过程展示（`thinking_*` 帧 →
可折叠思考分区，多段思考合并、结束后显示耗时）、会话自动创建与续聊
（`X-Conversation-Id` 优先 / 帧内 id 兜底）、停止生成（保留已收内容）、错误态与可读文案、
阻塞模式兜底重试、Markdown 渲染（sanitize + 高亮、代码块深色外壳）、复制、用量展示（单条 + 会话级汇总角标）、
会话侧边栏（新建 / 切换 / 删除，列表来自后端 `GET /conversations`）、历史消息加载（`GET /conversations/{id}/messages` 映射渲染）、
文件上传（本地校验 → 上传 → 预览 / 下载 / 删除）、<768px 响应式抽屉。
历史数据源切换（2026-08-26）：会话列表与消息快照的 localStorage 持久化已移除，改由后端历史接口提供。

**视觉重构（2026-08-25）**：页面按主流 AI 产品观感重写——明暗双主题 + 一键切换（默认跟随系统、
记忆偏好、首屏防闪白）、品牌渐变（靛蓝→紫→淡紫，去高饱和粉）、空态欢迎区（大标题 + 4 张建议
卡片点击即发送 + 光晕漂移动画）、玻璃输入卡 + 圆形渐变发送钮、助手渐变头像 / 用户渐变气泡 /
思考卡 shimmer、桌面侧栏折叠；功能与数据流零改动。

**不在 v1**：ToolCallCard / ArtifactLink 高级事件卡片——工具 / 产物事件仍为后端内部事件，不进入
对外正文（见关键契约确认）；若后端后续开放，再按 feature 开关接入。
