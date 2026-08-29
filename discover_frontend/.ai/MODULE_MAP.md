# 模块路径映射

> 模型记忆：职责 → 文件路径速查表。新增 / 删除模块文件后必须同步更新（见 `CLAUDE.md` 第 10 节）。

| 职责 | 文件 |
|---|---|
| 应用入口（createRoot + Root 根层 Toaster + 全局错误边界） | `src/main.tsx` |
| 应用壳层 + 页面编排（Cmd+K / 主题切换，不承载 Toaster） | `src/App.tsx` |
| Tailwind + 双主题设计令牌（深蓝黑 / 极简冷白）+ 玻璃拟态工具类 + 自定义工具类 + Markdown 样式 | `src/index.css` |
| 后端契约类型（pydantic 映射；含账号认证 AccountRecord / LoginResponse / AccountUsage / AvatarConfig / 资料请求体） | `src/types.ts` |
| 环境配置唯一入口（类型化 VITE_*） | `src/env.ts` |
| axios 实例 + 对话/历史/文件/助手接口封装 + 认证（login / fetchMe）+ 资料维护（fetchAccountUsage / fetchAvatarConfig / updateAccountName / uploadAvatar / changePassword / avatarUrl）+ Bearer 拦截器 + 全局 401 回调（HTTP 唯一出口） | `src/lib/api.ts` |
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
| 账号认证（status/account；resolveSession / login / applyAccount / logout / expire；登出重置 chat / conversations / assistants 防跨账号泄漏） | `src/stores/auth.ts` |
| 主题状态（localStorage `disf_theme` 单一事实源；登录页 / App 壳 / 根层 Toaster 共享） | `src/stores/theme.ts` |
| 视图状态（主区对话 / 用户中心 + 用户中心菜单个人中心 / 用量 + 当前会话 ID，localStorage `disf_view` / `disf_center_tab` / `disf_conversation_id` 持久化，刷新停留当前页面并恢复打开的对话；登出经 auth 复位回对话页） | `src/stores/view.ts` |
| shadcn 组件（button / dropdown-menu / input / skeleton / sonner） | `src/components/ui/*.tsx` |
| echarts 轻封装（按需装配 bar/line + grid/tooltip/legend + canvas；挂载初始化 / 卸载 dispose / resize） | `src/components/ui/chart.tsx` |
| 用户中心内容顶栏（返回钮 + 居中标题，对齐 ChatWindow 顶栏 h-14） | `src/components/PageHeader.tsx` |
| 用户中心（模仿 DeepSeek 开放平台布局：左菜单列 用量主区 + 左下角单独区域 个人中心 + 右侧内容区；菜单切换懒加载 Profile / Usage） | `src/components/UserCenter.tsx` |
| 认证闸门（loading → 登录页 → 主界面；main.tsx 包裹层） | `src/components/AuthGate.tsx` |
| 登录页（手机号 + 密码 → POST /auth/login 得 JWT） | `src/components/LoginScreen.tsx` |
| 品牌左栏（品牌 / 新对话 Ctrl+K / 助手 / 最近对话 / 底部账号区含头像展示 + 点击打开用户中心 + 主题 / 退出；桌面折叠 → 64px 图标轨道） | `src/components/Sidebar.tsx` |
| 个人中心内容区（用户中心左导航「个人中心」菜单切换进入，非独立页面；账号卡 + 账号信息只读行（昵称/手机号/注册时间/最近登录）+ 更换头像面板约束文案不常驻 + 修改密码点击展开；成功经 applyAccount 同步） | `src/components/ProfilePage.tsx` |
| 用量内容区（用户中心左导航「用量」菜单切换进入，非独立页面；模仿用量看板：聚合大值卡片 + 明细卡片 + ECharts 按日趋势图，趋势时间范围可切换 近 7/30/90 天；聚合 GET /users/me/usage，趋势 GET /users/me/usage/daily?days=） | `src/components/UsagePage.tsx` |
| 消息窗（顶栏：侧栏钮 + 标题脉冲 + 新对话 / 主题；turn 分组消息流 + 回合细线分隔 + 历史加载态） | `src/components/ChatWindow.tsx` |
| 空态（时段问候 + 探索方向助手卡片） | `src/components/EmptyState.tsx` |
| 悬浮输入区 composer（平铺助手胶囊 + Enter 发送 / 停止 / 长度校验 / 文件上传 / 免责声明 + 快捷键提示） | `src/components/ChatInput.tsx` |
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
