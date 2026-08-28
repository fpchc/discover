# 模块路径映射

> 模型记忆：职责 → 文件路径速查表。新增 / 删除模块文件后必须同步更新（见 `CLAUDE.md` 第 10 节）。

| 职责 | 文件 |
|---|---|
| 应用入口（createRoot + Root 根层 Toaster + 全局错误边界） | `src/main.tsx` |
| 应用壳层 + 页面编排（Cmd+K / 主题切换，不承载 Toaster） | `src/App.tsx` |
| Tailwind + 双主题设计令牌（深蓝黑 / 极简冷白）+ 玻璃拟态工具类 + 自定义工具类 + Markdown 样式 | `src/index.css` |
| 后端契约类型（pydantic 映射；含账号认证 AccountRecord / LoginResponse） | `src/types.ts` |
| 环境配置唯一入口（类型化 VITE_*） | `src/env.ts` |
| axios 实例 + 对话/历史/文件/助手接口封装 + 认证（login / fetchMe）+ Bearer 拦截器 + 全局 401 回调（HTTP 唯一出口） | `src/lib/api.ts` |
| 登录令牌持久化（localStorage `disf_auth_token` 读写，唯一事实源） | `src/lib/auth.ts` |
| 错误映射（HTTP + SSE error 帧） | `src/lib/errors.ts` |
| 历史消息映射（MessageRecord → ChatMessage，纯函数） | `src/lib/history.ts` |
| SSE 帧解析原语（纯函数） | `src/lib/sse.ts` |
| SSE 流读取 + 帧分发（readChatStream / consumeChatStream / readConversationId） | `src/lib/stream.ts` |
| cn() 工具（clsx + tailwind-merge） | `src/lib/utils.ts` |
| 对话发送 + 会话列表 / 助手目录 / 历史加载编排（send/stop/retry/cancel/openConversation/loadList/loadAssistants、agent_id 随发、metadata.assistant 回显、turn token、超时、卸载 abort 清理） | `src/hooks/useChatStream.ts` |
| 明暗主题 hook（只读壳：维护 `html.dark` / system 监听，状态在 `stores/theme.ts`） | `src/hooks/useTheme.ts` |
| 文件上传（上传配置校验 / 上传 / 列表 / 预览 URL） | `src/hooks/useFileUpload.ts` |
| 网络状态（online/offline） | `src/hooks/useNetworkStatus.ts` |
| 尾沿节流（流式 Markdown 降载，40ms） | `src/hooks/useThrottledValue.ts` |
| 对话状态（activeMessages 独立切片 / 流式状态，单一事实源，不可变更新） | `src/stores/chat.ts` |
| 会话列表（后端 `GET /conversations` 为唯一事实源，纯状态变更） | `src/stores/conversations.ts` |
| 助手目录 + 当前选择（`GET /assistants` 为目录源；选择随下一次 /chat-messages 生效） | `src/stores/assistants.ts` |
| 账号认证（status/account；resolveSession / login / logout / expire；登出重置 chat / conversations / assistants 防跨账号泄漏） | `src/stores/auth.ts` |
| 主题状态（localStorage `disf_theme` 单一事实源；登录页 / App 壳 / 根层 Toaster 共享） | `src/stores/theme.ts` |
| shadcn 组件（button / dropdown-menu / input / skeleton / sonner） | `src/components/ui/*.tsx` |
| 认证闸门（loading → 登录页 → 主界面；main.tsx 包裹层） | `src/components/AuthGate.tsx` |
| 登录页（手机号 + 密码 → POST /auth/login 得 JWT） | `src/components/LoginScreen.tsx` |
| 品牌左栏（品牌 / 新对话 Ctrl+K / 助手 / 最近对话 / 底部主题；桌面折叠 → 64px 图标轨道） | `src/components/Sidebar.tsx` |
| 消息窗（顶栏：侧栏钮 + 标题脉冲 + 新对话 / 主题；turn 分组消息流 + 回合细线分隔 + 历史加载态） | `src/components/ChatWindow.tsx` |
| 空态（时段问候 + 探索方向助手卡片） | `src/components/EmptyState.tsx` |
| 悬浮输入区 composer（Enter 发送 / 停止 / 长度校验 / 文件上传 / 助手胶囊 / 免责声明 + 快捷键提示） | `src/components/ChatInput.tsx` |
| 输入卡内助手选择器（shadcn 下拉：通用对话 + 专家） | `src/components/AssistantMenu.tsx` |
| 单条消息气泡（React.memo + 节流/deferred 降载 / 思考分区 / 状态徽章 / 结构化参数卡片 / 复制 / 重新生成 / 错误重试） | `src/components/MessageBubble.tsx` |
| 思考分区面板（进行中粒子流 + shimmer / 可折叠 / 耗时） | `src/components/ThinkingPanel.tsx` |
| 结构化参数展示（【键】值 → KV 卡片网格 / 胶囊流，避免露出 【】 字符） | `src/components/StructuredParams.tsx` |
| 状态徽章（thinking / generating / done / error / stopped，发光点 + 主题色） | `src/components/StatusBadge.tsx` |
| 结构化参数解析（纯函数：【键】值 → StructuredParam[]；开头参数段剥离） | `src/lib/structure.ts` |
| Markdown 渲染 + DOMPurify 清洗（hljs 按需高亮，流式期不高亮；代码块语言标签头 + 复制钮） | `src/components/Markdown.tsx` |
| Vitest 环境（jest-dom + matchMedia mock） | `src/test/setup.ts` |
| 应用冒烟渲染测试 | `src/App.test.tsx` |
| 纯逻辑 / store 单测 | `src/lib/*.test.ts` / `src/stores/*.test.ts` |
| 首屏防主题闪白（CSP 兼容经典脚本） | `public/theme-init.js` |
| Vite 装配（envDir ./env / server.proxy / outDir dist） | `vite.config.ts` |
| TS strict 配置（paths `@/*` → `src/*`） | `tsconfig.json` |
| 前端 Docker 多阶段构建 / nginx 模板 / 安全头 | `Dockerfile` / `nginx.conf` / `security-headers.conf`（项目根） |
| 后端 Docker 镜像 | `../discover_backend/Dockerfile` |
| 三环境全栈 compose | `../docker-compose.yml`（dev）/ `../docker-compose.prod.yml` / `../docker-compose.test.yml` |
| 环境模板（vite envDir 加载） | `env/.env.{example,development,test,production}` |
| CI（并行校验） | `.github/workflows/ci.yml` |
| lint+format 单一规则源 | `biome.json` |
| 单测（Vitest + Testing Library） | `vitest.config.ts` + `src/**/*.test.ts(x)` |
| 全局红线约束 | `CLAUDE.md` |
| 架构规范（依赖方向 / 边界） | `.claude/commands/architecture.md` |
| 性能与状态粒度红线（SSE 高频路径） | `.claude/commands/performance.md` |
| 需求文档 / API 契约 | `.claude/feature/REQUIREMENTS.md` / `.claude/feature/API.md` |
