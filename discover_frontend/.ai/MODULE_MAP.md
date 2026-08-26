# 模块路径映射

> 模型记忆：职责 → 文件路径速查表。新增 / 删除模块文件后必须同步更新（见 `CLAUDE.md` 第 9 节）。

| 职责 | 文件 |
|---|---|
| 应用壳层（NuxtPage 入口） | `app/app.vue` |
| 全局错误边界（客户端插件） | `app/plugins/globalErrorHandler.ts` |
| Nuxt 装配（`ssr:false` / devProxy / modules / 全局 CSS / head） | `nuxt.config.ts` |
| 环境配置唯一入口（类型化 VITE_*） | `app/config/env.ts` |
| 对话页编排 | `app/pages/index.vue` |
| 会话列表侧栏（新建 / 切换 / 删除 / 加载骨架） | `app/components/layout/AppSidebar.vue` |
| 消息窗（列表 + 空态 + 自动滚动 + 用量角标 + 助手选择器 + 历史加载态） | `app/components/layout/ChatWindow.vue` |
| 单条消息气泡（思考分区 / Markdown / 复制 / 用量 / 错误重试） | `app/components/chat/MessageBubble.vue` |
| 输入区（Enter 发送 / 停止 / 长度校验 / 文件上传附件） | `app/components/chat/ChatInput.vue` |
| 助手选择器（专家 / 通用对话显式选择，API.md §6） | `app/components/chat/AssistantPicker.vue` |
| 内联 SVG 图标库（手写，无图标依赖） | `app/components/common/AppIcon.vue` |
| 对话发送 + 会话列表 / 助手目录 / 历史加载编排（send/stop/retry/cancel/openConversation/loadList/loadAssistants、agent_id 随发、metadata.assistant 回显、turn token、超时） | `app/composables/useChatStream.ts` |
| Markdown 渲染 + DOMPurify 清洗（代码块深色外壳） | `app/composables/useMarkdown.ts` |
| 文件上传（上传配置校验 / 上传 / 列表 / 预览 URL） | `app/composables/useFileUpload.ts` |
| 网络状态（online/offline） | `app/composables/useNetworkStatus.ts` |
| 明暗主题（system 跟随 / 切换 / localStorage 记忆，维护 `html.dark`） | `app/composables/useTheme.ts` |
| 对话状态（消息 / 流式状态 / 用量汇总，单一事实源） | `app/stores/chat.ts` |
| 会话列表（后端 `GET /conversations` 为唯一事实源，纯状态变更） | `app/stores/conversations.ts` |
| 助手目录 + 当前选择（`GET /assistants` 为目录源；选择随下一次 /chat-messages 生效） | `app/stores/assistants.ts` |
| axios 实例（blocking / 历史 / 文件 HTTP 出口） | `app/api/client.ts` |
| 流式对话请求（fetch） | `app/api/chat.ts` |
| 历史接口（会话列表 / 消息流 / 用量汇总） | `app/api/history.ts` |
| 助手目录接口（专家 + 通用对话，API.md §6.1） | `app/api/assistants.ts` |
| 文件接口（上传配置 / 上传 / 预览 URL） | `app/api/files.ts` |
| 后端契约类型（pydantic 映射） | `app/api/types.ts` |
| 错误映射（HTTP + SSE error 帧） | `app/api/errors.ts` |
| SSE 帧解析原语（纯函数） | `app/utils/sse.ts` |
| 历史消息映射（MessageRecord → ChatMessage，纯函数） | `app/utils/history.ts` |
| 结构化日志 + 全局错误捕获 | `app/utils/logger.ts` |
| 双主题设计令牌（品牌渐变 / 表面 / 光效，EP 变量映射） | `app/styles/theme.css` |
| 全局样式 + Markdown 正文样式 | `app/styles/main.css` |
| 首屏防主题闪白（CSP 兼容经典脚本） | `public/theme-init.js` |
| 前端 Docker 多阶段构建 / nginx 模板 / 安全头 | `Dockerfile` / `nginx.conf` / `security-headers.conf`（本目录根） |
| 后端 Docker 镜像 | `../discover_backend/Dockerfile` |
| 三环境全栈 compose | `../docker-compose.yml`（dev）/ `../docker-compose.prod.yml` / `../docker-compose.test.yml` |
| 环境模板（`--dotenv` 加载，Nuxt 不采纳 vite.envDir） | `env/.env.{example,development,test,production}` |
| CI（并行校验） | `.github/workflows/ci.yml` |
| lint+format 单一规则源 | `biome.json` |
| 单测（Vitest） | `vitest.config.ts` + `app/**/*.spec.ts` |
| 全局红线约束 | `CLAUDE.md` |
| 架构规范（依赖方向 / 边界） | `.claude/commands/architecture.md` |
