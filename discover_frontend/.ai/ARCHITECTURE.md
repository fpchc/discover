# 架构快照

> 模型记忆：反映**当前**代码结构，与 `.claude/commands/architecture.md`（规范）互补。
> 结构变化后必须同步更新（见 `CLAUDE.md` 第 10 节）。

## 当前结构（2026-08-28 React 全量重构落地）

```
discover_frontend/
├── index.html                 入口 HTML（theme-init.js / lang=zh-CN / 标题）
├── vite.config.ts             Vite 装配：envDir ./env、server.proxy（读 VITE_PROXY_TARGET）、build.outDir=dist
├── src/
│   ├── main.tsx               应用入口（createRoot + Root 根层 Toaster + 全局错误边界 + 样式）
│   ├── App.tsx                应用壳层 + 页面编排（侧栏 / 主区 / 输入区串联 + Cmd+K + 主题切换；主区 view 状态切对话 / 用户中心两视图，用户中心内部以左导航切个人中心 / 用量；view 来自 stores/view.ts 持久化）
│   ├── index.css              Tailwind + 双主题设计令牌 + 自定义工具类 + Markdown 全局样式
│   ├── types.ts               后端契约类型（pydantic 映射，禁止组件内散落）
│   ├── env.ts                 环境配置唯一入口（类型化 VITE_*，禁止直读 import.meta.env）
│   ├── lib/                   纯逻辑层（叶子，无 React 依赖，可单测）
│   │   ├── api.ts             axios 实例 + 对话/历史/文件/助手接口封装 + 认证（login / refreshToken / logout / fetchMe）+ Bearer 拦截器 + 401→刷新重放拦截器 + 全局 401 回调（HTTP 唯一出口）
│   │   ├── auth.ts            登录令牌对持久化（localStorage `disf_auth_token` / `disf_auth_refresh_token` 成对读写，唯一事实源）
│   │   ├── errors.ts          错误映射（HTTP + SSE error 帧 → 可读文案）
│   │   ├── history.ts         MessageRecord → ChatMessage 映射（纯函数）
│   │   ├── sse.ts             SSE 帧解析原语（纯函数，data: 行 → 判别联合帧）
│   │   ├── stream.ts          流读取 + 帧分发（ReadableStream → 回调）
│   │   ├── structure.ts       「【键】值」结构化参数解析（纯函数：全文块 / 开头参数段剥离）
│   │   └── utils.ts           cn()（clsx + tailwind-merge）
│   ├── hooks/                 React 生命周期相关逻辑
│   │   ├── useChatStream.ts   对话发送 / 会话列表 / 助手目录 / 历史加载编排 + 卸载 abort 清理
│   │   ├── useTheme.ts        明暗主题 hook（只读壳：维护 html.dark / system 监听，状态在 stores/theme.ts）
│   │   ├── useFileUpload.ts   文件上传（配置校验 / 上传 / 列表 / 预览 URL）
│   │   ├── useNetworkStatus.ts 网络状态（online/offline）
│   │   └── useThrottledValue.ts 尾沿节流（流式 Markdown 降载）
│   ├── stores/                Zustand 单一事实源（跨组件共享状态唯一通道）
│   │   ├── chat.ts            当前会话：activeMessages（独立切片）/ conversationId / isStreaming / loadingHistory
│   │   ├── conversations.ts   会话列表（后端 GET /conversations 为唯一事实源）
│   │   ├── assistants.ts      助手目录 + 当前选择（agent_id）
│   │   ├── auth.ts            账号认证（status/account；resolveSession / login / logout / expire；登录写令牌对、登出调后端作废、过期清令牌对；登出重置 chat / conversations / assistants / view 四 store）
│   │   ├── theme.ts           主题状态（localStorage `disf_theme` 单一事实源；登录页 / App 壳 / 根层 Toaster 共享）
│   │   └── view.ts            视图状态（主区对话 / 用户中心 + 用户中心菜单 + 当前会话 ID；localStorage `disf_view` / `disf_center_tab` / `disf_conversation_id` 持久化，刷新停留当前页面并恢复打开的对话）
│   ├── components/
│   │   ├── ui/                shadcn 拷入组件（button / dropdown-menu / input / skeleton / sonner）+ chart.tsx（echarts 轻封装）
│   │   ├── AuthGate.tsx       认证闸门（loading → 登录页 → 主界面；main.tsx 包裹层）
│   │   ├── LoginScreen.tsx    登录页（手机号 + 密码 → POST /auth/login）
│   │   ├── Sidebar.tsx        品牌左栏（品牌 / 新对话 Ctrl+K / 助手 / 最近对话 / 底部账号区 + 退出 / 底部主题；桌面折叠 → 64px 图标轨道）
│   │   ├── PageHeader.tsx     用户中心内容顶栏（返回钮 + 居中标题，h-14 对齐 ChatWindow）
│   │   ├── UserCenter.tsx     用户中心（模仿 DeepSeek 开放平台布局：左菜单列 个人中心 / 用量 + 右侧内容区；菜单切换懒加载 Profile / Usage）
│   │   ├── ProfilePage.tsx    个人中心内容区（非独立页面；头像只读 + 更换头像面板 + 修改密码点击展开）
│   │   ├── UsagePage.tsx      用量内容区（非独立页面；模仿用量看板：聚合卡片 + ECharts 按日趋势图）
│   │   ├── ChatWindow.tsx     消息窗（顶栏 + turn 分组消息流 + 回合细线分隔 + 历史加载态）
│   │   ├── EmptyState.tsx     空态（时段问候 + 探索方向助手卡片）
│   │   ├── ChatInput.tsx      悬浮输入区 composer（平铺助手胶囊 + Enter 发送 / 停止 / 长度校验 / 文件上传 / 免责声明）
│   │   ├── MessageBubble.tsx  消息气泡（React.memo + 节流/deferred 降载；思考分区 / 结构化参数卡片 / 状态徽章 / 复制 / 重新生成 / 重试）
│   │   ├── ThinkingPanel.tsx  思考分区（进行中粒子流 + shimmer / 可折叠 / 结束显示耗时）
│   │   ├── StructuredParams.tsx 结构化参数展示（【键】值 → KV 卡片网格 / 胶囊流）
│   │   ├── StatusBadge.tsx    状态徽章（thinking / generating / done / error / stopped，发光点）
│   │   └── Markdown.tsx       react-markdown + remark-gfm + hljs 按需高亮 + DOMPurify（代码块复制钮）
│   └── test/setup.ts          Vitest 环境（jest-dom + matchMedia mock）
├── env/                       环境模板（vite envDir 加载）：.env.example / .development / .test / .production
├── public/theme-init.js       首屏防主题闪白（CSP 兼容经典脚本，读取 disf_theme）
└── 根配置                      package.json / tsconfig.json / vitest.config.ts / biome.json / Dockerfile / nginx.conf
```

## 关键设计决策

| 决策 | 选型 | 理由 |
|---|---|---|
| 框架层 | **Vite + React 19（纯客户端 SPA）** | 构建 / dev 唯一入口；渲染在浏览器端，静态产物 `dist/`，部署保持 nginx 静态托管；无 SSR / 水合负担 |
| 样式 | **Tailwind CSS 4**（`@theme`，CSS-first，无 tailwind.config.js） | 设计令牌全走 CSS 变量；`@utility` 封装品牌渐变 / 辉光阴影 |
| 组件原语 | **shadcn/ui**（Radix + Tailwind，拷入 `src/components/ui/`） | 样式归本项目、a11y 由 Radix 兜底；toast 用 sonner，图标用 lucide-react |
| 状态共享 | **Zustand**（`src/stores/`） | 粒度订阅；`activeMessages` 独立切片与历史列表解耦（性能红线） |
| SSE | fetch + ReadableStream | POST 语义；解析原语在 `lib/sse.ts`，读取/分发在 `lib/stream.ts` |
| 流式编排 | `useChatStream` hook 驱动 store | store 只做状态与变更，HTTP/SSE/取消/超时/retry 全在编排层；turn token 作废旧流防幽灵增量；**组件卸载 useEffect cleanup 调 abort()** |
| 流式渲染降载 | `MessageBubble` React.memo + `useThrottledValue`（40ms 尾沿节流）+ `useDeferredValue` | 历史消息绝不随流式重渲；Markdown 高亮仅在收尾后执行（performance.md §2） |
| Markdown | react-markdown + remark-gfm + highlight.js 按需注册 7 语言 + DOMPurify | 默认不渲染原始 HTML（安全收敛）；代码块深色外壳 + 语言标签头 + 复制钮 |
| 图表 | **echarts**（按需装配 bar/line + grid/tooltip/legend + canvas，`ui/chart.tsx` 轻封装） | 用量页「尽量用图展示」新增（用户明确指示，CLAUDE.md §1 硬约束逃逸）；配色经 dataviz 校验明暗均通过 |
| 错误映射 | `lib/errors.ts` 集中维护 | HTTP 状态码 + SSE error 帧 → 可读文案一处收口 |
| 账号认证 | 令牌对（`POST /auth/login` 返回 access + refresh）+ axios Bearer 拦截器 + 401→刷新重放拦截器（并发单飞 / 轮换写回 / 失败才全局过期）+ `AuthGate` 闸门 + 侧栏账号区/退出 + 服务端登出（`POST /auth/logout`） | 后端 `ACCOUNT_API.md` 引入账号体系（手机号+密码登录，数据按账号隔离；Redis 会话权威）；令牌对存 localStorage `disf_auth_token` / `disf_auth_refresh_token`（access 24h / refresh 7d 轮换制），启动 `resolveSession` 用 `GET /users/me` 校验；受保护接口 401 先刷新重放、刷新失败才回登录页；登出/过期重置 chat / conversations / assistants / view 四 store 防跨账号数据泄漏 |
| 视图持久化 | Zustand `stores/view.ts` + localStorage `disf_view` / `disf_center_tab` / `disf_conversation_id` | 仅 UI 导航状态（对话 / 用户中心 + 个人中心 / 用量 + 当前会话指针），刷新停留当前页面并恢复打开的对话（App 挂载加载列表后重开）；不存会话正文数据（后端为事实源）；登出 / 过期经 `resetAppState` 复位回对话页 |
| Toast 挂载 | Toaster 常驻根层（`main.tsx` Root，在 `AuthGate` 之上） | 登录页与主界面互斥挂载，toast 若挂在任一侧，登录成功切屏即随卸载消失；根层保证登录错误 / 成功提示跨屏可见。主题经 `stores/theme.ts` 全局共享，根层 Toaster 与任一屏的主题切换实时同步 |
| 显式助手选择 | `GET /assistants` 目录 + 请求体 `agent_id` + `message_end`/blocking `metadata.assistant` 回显 | 用户显式选专家，选择随下一次发送生效（API.md §3）；入口统一为输入卡上方平铺专家助手胶囊（未选中即默认，目录内 generic 项过滤，无「通用对话」下拉项），侧栏「技能与助手」为新建绑定专家会话的快捷入口 |
| 历史数据源 | 后端历史接口（`GET /conversations`、`/conversations/{id}/messages`，见 `.claude/feature/API.md`） | 会话列表 / 消息以后端为唯一事实源，前端不持久化；新会话乐观入列，回合结束后 `reconcileList` 校准 |
| 文件上传 | `useFileUpload` hook + ChatInput 附件（`GET|POST /files/upload`、`GET /files/{id}/preview`） | 上传前本地校验扩展名 / 大小；图片内联缩略、其余新窗口 / `a[download]` |
| 环境 | VITE_* 收容 `env/`，vite `envDir` 原生注入 `import.meta.env`（`src/env.ts` 收窄） | 与 Nuxt 不同无需 `--dotnet`；配置驱动、无硬编码、无密钥模板提交 |
| 视觉体系 | 深蓝黑科技（dark 旗舰：`#0F172A` 系 + 荧光青 `#22d3ee` 点亮）+ 极简冷白（light：`#FAFAFA`）双主题；玻璃拟态（`@utility glass-panel/surface/sidebar`：`backdrop-filter: blur()` + 1px 微发光边框 + 内顶高光）落在输入区 / 侧栏 / 思考分区 / 登录卡；对话主体 800px 居中；会话 HUD 数据卡条（助手 / 消息数 / 回合数 / 生成状态，纯前端真实状态）；「【键】值」结构化参数自动渲染为 KV 卡片网格 / 胶囊（`lib/structure.ts` → `StructuredParams`），不再露出 【】 字符；侧栏会话项悬停渐变微光（`.conv-item`）；AI 回复流式阶段 / 完成态用 `StatusBadge` | 品牌渐变只落主按钮 / 发送钮 / 头像 / 选中态；shadcn 变量映射主题令牌；`theme-init.js` 首屏防闪白；全部色值走 `--xxx` 令牌，不硬编码 |
| 代码块 | highlight.js 统一 `github-dark`，`.codeblock` 深色外壳 + 语言标签头 + 复制钮 | 明暗主题一致；`Markdown.tsx` 自定义 `pre` 渲染器（流式期不高亮，收尾后高亮 + 可复制） |
| 校验 | Biome（Rust，lint+format 单一源）+ `tsc --noEmit` | 类型检查基线；`--error-on-warnings` 门禁 |
| 部署 | 多阶段 Docker + nginx（静态托管 `dist/`，`/assets/` hash 长缓存，`/api` 反代 SSE 优化） | 同源 SSE 反代、长缓存、CSP；`Dockerfile` / `nginx.conf` 在项目根，全栈 compose 在仓库根 |

## 关键契约确认（2026-08-24 起与后端对齐，React 重构后保持不变）

* **账号认证（ACCOUNT_API.md，2026-08-28 新增；Redis 会话 2026-08-29 落地）**：`POST /api/v1/auth/login`
  （手机号+密码）与 `/auth/login/elecnest`、`/auth/refresh` 均返回令牌对
  `{account_id, token, refresh_token, expires_in, name?}`；访问令牌 `token`（Bearer，Redis 权威，
  key 24h）、刷新令牌 `refresh_token`（7d，轮换制每次刷新换新）；`/auth/logout`（Bearer + body refresh）
  服务端作废令牌对（DEL 幂等，204）。除 `/auth/*`、`GET /assistants`、`GET /files/upload`、
  `GET /files/{file_id}/preview` 外，**数据接口一律需 `Authorization: Bearer <token>` 且按账号隔离**
  （跨账号读/删/续聊 → 404，不泄露存在性）。令牌对存 localStorage `disf_auth_token` /
  `disf_auth_refresh_token`，启动用 `GET /users/me` 校验恢复；受保护接口 401 先单飞刷新重放一次，
  **刷新成功即不跳登录页**，刷新失败才 `setUnauthorizedHandler` → `expire` 全局回登录页。
* **登录失败** 统一 401 `{detail: "手机号或密码错误"}`（防账号枚举）；非 `is_system` 访问 `GET /users` → 403。

* **SSE 判别帧共 7 种**：`message` / `message_end` / `ping` / `error` + 思考三帧
  `thinking_started` / `thinking_delta` / `thinking_ended`（`chat.py:_stream_sse` 映射）。
* **思考已对外**：`thinking_*` 帧携带思考过程（`thinking_delta.content` 增量、`thinking_ended.duration_ms`），
  前端渲染为可折叠思考分区（`MessageBubble` 内），由 `VITE_FEATURE_THINKING` 开关控制显示。工具走 `tool_call_*`、
  产物走 `artifact_ready` 仍为后端**内部**事件，不进入对外正文；ToolCallCard / ArtifactLink 保持不在 v1。
* **HTTP 错误体**：PlatformError `{error:{category,message}}` / FastAPI `{detail}`。
* **SSE 帧 `created_at` 为 epoch 秒**；历史接口记录 `created_at` 为 ISO 8601（pydantic 序列化）。
* **历史 / 文件接口**（API.md §1 / §2）：会话列表、消息流由后端提供；产物下载接口
  `/sessions/{sid}/artifacts/{aid}` 已移除，预览 / 下载改走 `GET /api/v1/files/{file_id}/preview`。
* **助手选择**（API.md §3）：`GET /assistants` 返回 `{id,type,name,description,capabilities}`（expert + generic，
  generic 为保留字）；请求体可选 `agent_id`（首轮绑定 / 续聊沿用 / `"generic"` 切回通用 / 未知 id → 404）；
  `message_end` 与 blocking 的 `metadata.assistant` 回显当前回合生效助手
  （`{"type":"expert","id":"discover"}` / `{"type":"generic","id":null}` / 缺失 = 新会话未绑定）。
  `select_agent` / `select_skill` 已移除，模型不再决定进哪个助手。

## 已知限制

- **react-markdown 不渲染原始 HTML**（安全收敛），故模型输出中的原生 HTML 标签会被跳过而非渲染。
- **单 chunk 785KB（gzip 251KB）**：react-dom + motion + radix 体积合理；`chunkSizeWarningLimit` 已调至 800。
  若后续继续增大，可考虑 `build.rolldownOptions.output.codeSplitting` 拆 vendor 或按路由懒加载。
- 本机开发若配置了系统代理（`HTTP_PROXY`），访问 localhost 需经 `--noproxy` 或浏览器 `NO_PROXY`。

## 当前能力边界（v1 功能已落地）

对话全流程可用：发送（Enter/Shift+Enter、长度校验）、流式打字机、思考过程展示（`thinking_*` 帧 →
可折叠思考分区，多段思考合并、结束后显示耗时）、会话自动创建与续聊
（`X-Conversation-Id` 优先 / 帧内 id 兜底）、停止生成（保留已收内容）、错误态与可读文案、
阻塞模式兜底重试、Markdown 渲染（sanitize + 高亮、代码块语言标签头 + 复制钮）、
消息流 turn 分组（用户 + 助手一回合，回合间细线分隔）、流式状态行（深度思考 / 生成中）、
最后一条已完成助手消息可「重新生成」、会话侧边栏（新建 / 切换 / 删除 / 桌面折叠图标轨道，
列表来自后端 `GET /conversations`）、空态（时段问候 + 探索方向卡片点选即建绑定会话）、
历史消息加载（`GET /conversations/{id}/messages` 映射渲染）、
文件上传（本地校验 → 上传 → 预览 / 下载 / 删除）、<768px 响应式抽屉。

**显式助手选择**：`GET /assistants` 目录为选择来源，用户显式选专家，每次发消息带 `agent_id`
（首轮绑定 / 续聊切换），回合结束按 `metadata.assistant` 回显选择器；打开历史会话按 `ConversationRecord.agent_id` 对齐选择器。
首选入口统一为输入卡上方平铺专家助手胶囊（未选中任何专家即默认，目录内 `generic` 项过滤），侧栏「技能与助手」点选专家 = 新建绑定该助手的工作会话。

**性能红线落地（React 重构）**：`MessageBubble` `React.memo`（App 事件回调 `useCallback` 稳定引用，保证 memo 生效）；
流式正文 `useThrottledValue`（40ms）+ `useDeferredValue` 双重降载 + 收尾才高亮；
`activeMessages` 独立切片，侧栏只订阅 `items/loading/selectedId`；`useChatStream` 卸载 `abort()` + turn 作废防幽灵增量。

**视觉 / 排版升级（2026-08-28 整体 UI 重构）**：双主题令牌改版（dark `#0F172A` 深蓝黑 + 荧光青，
light `#FAFAFA` 极简冷白）；玻璃拟态工具类（`glass-panel / glass-surface / glass-sidebar`）落地输入区 /
侧栏 / 思考分区 / 登录卡 / 空态卡；对话主体收紧 800px 居中 + 会话 HUD 数据卡条；
「【键】值」结构化参数 → KV 卡片 / 胶囊（用户输入全文解析、AI 回复开头参数段剥离，`lib/structure.ts`
纯函数 + `StructuredParams`）；AI 回复流式阶段 / 完成态 `StatusBadge`；
思考分区抽成 `ThinkingPanel`（粒子流 + 可折叠 + 耗时）；侧栏会话项 `.conv-item` 悬停渐变微光。

**不在 v1**：ToolCallCard / ArtifactLink 高级事件卡片——工具 / 产物事件仍为后端内部事件，不进入
对外正文（见关键契约确认）；若后端后续开放，再按 feature 开关接入。
