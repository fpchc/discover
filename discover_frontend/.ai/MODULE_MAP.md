# 模块路径映射

> 模型记忆：职责 → 文件路径速查表。新增 / 删除模块文件后必须同步更新（见 `CLAUDE.md` 第 9 节）。

| 职责 | 文件 |
|---|---|
| 入口 / 全局错误边界 / 插件装配 | `src/main.ts` |
| 应用壳层 | `src/App.vue` |
| 环境配置唯一入口（类型化 VITE_*） | `src/config/env.ts` |
| 路由（ChatView 懒加载） | `src/router/index.ts` |
| 对话页编排 | `src/views/ChatView.vue` |
| 会话列表侧栏（新建 / 切换 / 删除 / 加载骨架） | `src/components/layout/AppSidebar.vue` |
| 消息窗（列表 + 空态 + 自动滚动 + 用量角标 + 历史加载态） | `src/components/layout/ChatWindow.vue` |
| 单条消息气泡（思考分区 / Markdown / 复制 / 用量 / 错误重试） | `src/components/chat/MessageBubble.vue` |
| 输入区（Enter 发送 / 停止 / 长度校验 / 文件上传附件） | `src/components/chat/ChatInput.vue` |
| 内联 SVG 图标库（手写，无图标依赖） | `src/components/common/AppIcon.vue` |
| 对话发送 + 会话列表 / 历史加载编排（send/stop/retry/cancel/openConversation/loadList、turn token、超时） | `src/composables/useChatStream.ts` |
| Markdown 渲染 + DOMPurify 清洗（代码块深色外壳） | `src/composables/useMarkdown.ts` |
| 文件上传（上传配置校验 / 上传 / 列表 / 预览 URL） | `src/composables/useFileUpload.ts` |
| 网络状态（online/offline） | `src/composables/useNetworkStatus.ts` |
| 明暗主题（system 跟随 / 切换 / localStorage 记忆，维护 `html.dark`） | `src/composables/useTheme.ts` |
| 对话状态（消息 / 流式状态 / 用量汇总，单一事实源） | `src/stores/chat.ts` |
| 会话列表（后端 `GET /conversations` 为唯一事实源，纯状态变更） | `src/stores/conversations.ts` |
| axios 实例（blocking / 历史 / 文件 HTTP 出口） | `src/api/client.ts` |
| 流式对话请求（fetch） | `src/api/chat.ts` |
| 历史接口（会话列表 / 消息流 / 用量汇总） | `src/api/history.ts` |
| 文件接口（上传配置 / 上传 / 预览 URL） | `src/api/files.ts` |
| 后端契约类型（pydantic 映射） | `src/api/types.ts` |
| 错误映射（HTTP + SSE error 帧） | `src/api/errors.ts` |
| SSE 帧解析原语（纯函数） | `src/utils/sse.ts` |
| 历史消息映射（MessageRecord → ChatMessage，纯函数） | `src/utils/history.ts` |
| 结构化日志 + 全局错误捕获 | `src/utils/logger.ts` |
| 双主题设计令牌（品牌渐变 / 表面 / 光效，EP 变量映射） | `src/styles/theme.css` |
| 全局样式 + Markdown 正文样式 | `src/styles/main.css` |
| 首屏防主题闪白（CSP 兼容经典脚本） | `public/theme-init.js` |
| 前端 Docker 多阶段构建 / nginx 模板 / 安全头 | `Dockerfile` / `nginx.conf` / `security-headers.conf`（本目录根） |
| 后端 Docker 镜像 | `../discover_backend/Dockerfile` |
| 三环境全栈 compose | `../docker-compose.yml`（dev）/ `../docker-compose.prod.yml` / `../docker-compose.test.yml` |
| 环境模板（envDir=./env） | `env/.env.{example,development,test,production}` |
| CI（并行校验） | `.github/workflows/ci.yml` |
| lint+format 单一规则源 | `biome.json` |
| 全局红线约束 | `CLAUDE.md` |
| 架构规范（依赖方向 / 边界） | `.claude/commands/architecture.md` |
