# 模块路径映射

> 模型记忆：职责 → 文件路径速查表。新增 / 删除模块文件后必须同步更新（见 `CLAUDE.md` 第 9 节）。

| 职责 | 文件 |
|---|---|
| 入口 / 全局错误边界 / 插件装配 | `src/main.ts` |
| 应用壳层 | `src/App.vue` |
| 环境配置唯一入口（类型化 VITE_*） | `src/config/env.ts` |
| 路由（ChatView 懒加载） | `src/router/index.ts` |
| 对话页编排 | `src/views/ChatView.vue` |
| 会话列表侧栏（新建 / 切换 / 删除） | `src/components/layout/AppSidebar.vue` |
| 消息窗（列表 + 空态 + 自动滚动） | `src/components/layout/ChatWindow.vue` |
| 单条消息气泡（Markdown / 复制 / 用量 / 错误重试） | `src/components/chat/MessageBubble.vue` |
| 输入区（Enter 发送 / 停止 / 长度校验） | `src/components/chat/ChatInput.vue` |
| SSE 帧消费 + 发送编排（send/stop/retry/cancel、turn token、超时） | `src/composables/useChatStream.ts` |
| Markdown 渲染 + DOMPurify 清洗 | `src/composables/useMarkdown.ts` |
| 网络状态（online/offline） | `src/composables/useNetworkStatus.ts` |
| 对话状态（单一事实源） | `src/stores/chat.ts` |
| 会话列表 + 本地持久化 | `src/stores/conversations.ts` |
| axios 实例（blocking HTTP 出口） | `src/api/client.ts` |
| 流式对话请求（fetch） | `src/api/chat.ts` |
| 后端契约类型（pydantic 映射） | `src/api/types.ts` |
| 错误映射（HTTP + SSE error 帧） | `src/api/errors.ts` |
| SSE 帧解析原语（纯函数） | `src/utils/sse.ts` |
| localStorage 封装（`disf_` 前缀） | `src/utils/persist.ts` |
| 结构化日志 + 全局错误捕获 | `src/utils/logger.ts` |
| 全局样式 | `src/styles/main.css` |
| 前端 Docker 多阶段构建 / nginx 模板 / 安全头 | `Dockerfile` / `nginx.conf` / `security-headers.conf`（本目录根） |
| 后端 Docker 镜像 | `../discover_backend/Dockerfile` |
| 三环境全栈 compose | `../docker-compose.yml`（dev）/ `../docker-compose.prod.yml` / `../docker-compose.test.yml` |
| 环境模板（envDir=./env） | `env/.env.{example,development,test,production}` |
| CI（并行校验） | `.github/workflows/ci.yml` |
| lint+format 单一规则源 | `biome.json` |
| 全局红线约束 | `CLAUDE.md` |
| 架构规范（依赖方向 / 边界） | `.claude/commands/architecture.md` |
