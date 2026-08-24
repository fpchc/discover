# 架构快照

> 模型记忆：反映**当前**代码结构，与 `.claude/commands/architecture.md`（规范）互补。
> 结构变化后必须同步更新（见 `CLAUDE.md` 第 9 节）。

## 当前结构（2026-08-24 骨架落地）

```
discover_frontend/
├── env/                        # 环境模板（vite envDir=./env）：.env.example / .development / .test / .production
├── .github/workflows/ci.yml    # CI 并行：lint / typecheck / test / build
├── src/
│   ├── main.ts                 入口：全局错误边界 + Pinia + Router + Element Plus
│   ├── App.vue                 壳层（RouterView）
│   ├── env.d.ts                VITE_* 类型声明
│   ├── config/env.ts           环境配置唯一入口（类型化收窄，禁止直读 import.meta.env）
│   ├── router/index.ts         路由（ChatView 懒加载）
│   ├── views/ChatView.vue      页面编排
│   ├── components/
│   │   ├── layout/             AppSidebar / ChatWindow
│   │   ├── chat/               ChatInput / MessageBubble
│   │   └── common/             （预留）
│   ├── composables/            useChatStream / useMarkdown / useNetworkStatus
│   ├── stores/                 chat / conversations
│   ├── api/                    client / chat / types / errors
│   ├── utils/                  sse / persist / logger
│   └── styles/main.css
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
| 消息快照 | localStorage `disf_snap_<cid>` | 仅已完成消息落盘（中断不落），刷新 / 切换按会话恢复 |
| 环境 | VITE_* 收容 `env/`，`envDir: ./env` | 三环境模板、配置驱动、无硬编码 |
| 校验 | Biome（Rust，lint+format 单一源） | 替代 ESLint+Prettier，消除规则重叠 |
| 部署 | 多阶段 Docker + nginx（各子项目自带构建文件） | 同源 SSE 反代、hash 长缓存、CSP；`Dockerfile` / `nginx.conf` 在各自项目根，全栈 compose 在仓库根 |
| 会话持久化 | localStorage（`disf_` 前缀） | 仅元数据，不存消息全文 |

## 关键契约确认（2026-08-24，与后端对齐）

* **SSE 判别帧仅 4 种**：`message` / `message_end` / `ping` / `error`（`routes_chat.py:_stream_sse`）。
* **`message` 帧 `answer` 为纯文本增量**：thinking 走 `thinking_delta`、工具走 `tool_call_*`、产物走
  `artifact_ready`，均为后端**内部**事件，不进入对外正文。据此需求 §3 契约澄清落地为 **M2–M4 保持纯正文
  展示**，前端不虚构事件消费组件；`VITE_FEATURE_*` 开关为后端开放结构化片段后的预留配置（当前未消费）。
* **HTTP 错误体**：PlatformError `{error:{category,message}}` / FastAPI `{detail}`。
* **`created_at` 为 epoch 秒**；`message_end.metadata.usage` = `{prompt_tokens, completion_tokens, total_tokens}`。

## 已知限制

- **Biome 对 Vue**：暂不识别 `<script setup>` 模板绑定，故 `biome.json` 对 `.vue` 关闭
  `noUnusedVariables` / `noUnusedImports`（避免误删模板引用变量）；TS 文件仍启用。
- Element Plus 全量引入（约 916 kB chunk），后续可切 `unplugin-vue-components` 按需引入。

## 当前能力边界（v1 功能已落地）

对话全流程可用：发送（Enter/Shift+Enter、长度校验）、流式打字机、会话自动创建与续聊
（`X-Conversation-Id` 优先 / 帧内 id 兜底）、停止生成（保留已收内容）、错误态与可读文案、
阻塞模式兜底重试、Markdown 渲染（sanitize + 高亮）、复制、用量展示、会话侧边栏
（新建 / 切换 / 删除 / 本地持久化 + 消息快照）、<768px 响应式抽屉、跨标签 storage 同步。

**不在 v1**：M2–M4 高级事件卡片（ThinkingBlock/ToolCallCard/ArtifactLink）——后端暂不外泄这些
内部事件，正文为纯文本（见关键契约确认）；若后端后续在正文输出结构化片段，再按 feature 开关接入。
