# CLAUDE.md — discover_frontend 全局红线约束

> 本文件是前端项目的全局硬约束，与后端 `discover_backend/CLAUDE.md` 同构：只写可判定的红线。
> 架构 / 目录结构 / 模块职责等结构性说明放 `.claude/commands/architecture.md`；
> 流式渲染性能与状态粒度红线放 `.claude/commands/performance.md`；架构快照与模块映射存 `.ai/*.md`。
> 详细需求与交互细节见 `.claude/feature/REQUIREMENTS.md`；后端接口契约见 `.claude/feature/API.md`。
> **逃逸机制**：本文件所有规则在严格遵循会导致过度设计时，允许实用主义简化，但必须在代码处标注
> `// pragma: 简化 — <原因>`。无标注的偏离视为违规。
>
> **对话边界（可判定硬约束，不可逃逸，无 `// pragma` 例外）**：全部工作与工具调用
> （Bash / Read / Glob / Grep / ls / find 等）只允许落在当前仓库目录 `discover_frontend` 内；
> 没有用户明确授权 / 运行，禁止扫描、读取、列出目录外任何文件——含兄弟仓库 `discover_backend`、
> 桌面、用户目录、`.git`、父目录、其他盘符、图片、剪贴板、临时目录等。需要外部信息时
> 向用户说明并请其提供（或用户授权后再动），不得自行越界读取。

## 0. 项目定位

* 框架层采用 **Vite + React 19（纯客户端 SPA）**：Vite 承担构建 / dev server / 模块装配唯一入口，
  渲染始终发生在浏览器端，静态产物输出 `dist/`，部署保持 nginx 静态托管（见第 1、4 节）。
* 后端为 `discover_backend`（多智能体承载平台），对话走 `POST /api/v1/chat-messages`。
* 前端**只消费已有 API**，不新增后端接口；会话列表 / 消息历史由后端历史接口提供
  （`GET /conversations`、`GET /conversations/{id}/messages`），文件走 `GET|POST /files/upload`
  与 `GET /files/{id}/preview`；前端不做会话数据本地持久化（见第 11 节）。

## 1. 技术栈（固定，不可替换，不可新增未列出的同类库）

| 技术 | 约束 |
|---|---|
| **React 19** | 函数组件 + Hooks；禁止 class 组件混用 |
| **TypeScript（strict）** | 见第 2 节；`pnpm typecheck`（`tsc --noEmit`）作为类型检查基线 |
| **Vite** | 构建 / dev server 唯一入口；`build.outDir='dist'` 静态产物；`server.proxy` 承担 dev 代理（读 `VITE_PROXY_TARGET`） |
| **Tailwind CSS 4** | CSS-first 配置（`@theme`，无 `tailwind.config.js`）；样式语言唯一来源，禁止 CSS Modules / styled-components |
| **shadcn/ui**（Radix + Tailwind） | 组件原语唯一来源（拷入 `src/components/ui/`，样式归本项目掌控）；`cn()` = `clsx` + `tailwind-merge` |
| **motion**（前 framer-motion） | 微交互动画唯一实现（消息入场、侧栏抽屉、空态、thinking shimmer）；禁止引入其它动画库 |
| **Zustand** | 跨组件共享状态唯一通道（第 3 节）；替代旧 Pinia |
| **react-router** | 页面路由唯一实现（纯客户端 BrowserRouter，CLAUDE.md 第 1 节）；五条页面路由，URL 为页面导航唯一事实源，禁止再造非路由的页面状态切换（如旧 view/centerTab） |
| **axios** | 普通 HTTP（blocking 模式）唯一出口，统一实例在 `src/lib/api.ts` |
| **fetch + ReadableStream** | SSE 唯一实现方式。`POST` 无法用 `EventSource`，禁止 `EventSource` |
| **react-markdown + remark-gfm + rehype-highlight** | Markdown 渲染唯一实现；默认不渲染原始 HTML（安全收敛，见第 6 节） |
| **DOMPurify** | 任何 `dangerouslySetInnerHTML` 边界必须经它清洗（渲染红线见第 6 节） |
| **sonner** | toast 唯一实现（替代旧 ElMessage） |
| **lucide-react** | 图标唯一来源（替代旧手写 SVG） |
| **Biome** | lint / format 单一规则源 |
| **Vitest + @testing-library/react** | 单测框架（SSE 解析、历史映射、store、组件） |

以下两条为**可判定硬约束，逃逸机制（`// pragma`）不适用**：

* **纯客户端 SPA 固定**。不引入 SSR / 水合；所有浏览器 API（`fetch` + `ReadableStream`、
  `AbortController`、`navigator`、`window`）天然在客户端作用域，无需守卫。引入 SSR 属架构变更。
* 未列入本表的同类库（状态管理、HTTP、Markdown、UI、动画、图标、Lint/Format、测试框架）一律不得新增。

包管理器 `pnpm`；Node `>= 20`（建议 22 LTS）。React 19 / Tailwind v4 / motion 的 peerDependencies
在脚手架阶段已验证（见 `.claude/commands/performance.md` §4）。

## 2. 语言与类型

* **全量显式标注**：所有函数、props、hooks 返回值、store state/action 的入参与返回必须显式类型；
  禁止依赖 IDE / 默认值推断。
* **业务代码显式 import**：允许 Vite 的自动注入能力（`import.meta.env` 经 `src/env.ts` 收窄），
  但业务代码一律显式 import，禁止依赖隐性全局绑定，避免歧义。
* **禁止 `any` 规避检查**：与后端契约对齐的类型集中定义于 `src/types.ts`（映射后端 pydantic 模型），
  禁止在组件内散落重复定义。仅在与无类型第三方库的边界允许 `any`，需 `// pragma: 简化 — <原因>`。
* **禁止裸 `as` 断言**绕过检查：仅 `JSON.parse` 等运行时边界允许，且必须带类型收窄说明注释。
* **`!` 非空断言**：仅当在运行时用上游逻辑保证非空时允许，并注释依据；禁止用来掩盖未初始化缺陷。
* **接口用 `interface`，联合/工具类型用 `type`**：对齐后端 pydantic 判别联合。

## 3. 状态与数据流（Zustand）

* 跨组件共享状态一律 Zustand store（`src/stores/chat.ts`、`src/stores/conversations.ts`、
  `src/stores/assistants.ts`）；禁止组件间互引状态 / 全局事件总线。
* **Active Chat 与 History 分离**：当前正在输入的会话 `activeMessages: ChatMessage[]` 独立切片
  （`chat` store 内 slice），与历史列表 `conversations.items` 解耦；流式增量只写 `activeMessages`，
  不触碰会话列表。
* **粒度订阅（性能红线）**：组件用 selector 只订阅自己需要的切片，禁止整体订阅大 store。
  侧栏只订阅 `conversations` 的 `items / loading / selectedId`，**禁止订阅 `activeMessages`**；
  流式逐字符增量不得触发侧栏等无关组件重渲。见 `.claude/commands/performance.md`。
* **props 单向数据流**：子组件通过 `props` 收数据、事件回调上报，禁止直接改写 props / 直写 store。
* 流式对话过程中，消息增量必须写入 Zustand（单一事实源），组件只做渲染，禁止组件持有对话副本。
* 纯展示组件用受控模式由父组件托管状态；禁止在子组件内 `useEffect` 后修改共享状态造成环路。

## 4. API 与网络

* 所有 HTTP 出口统一走 `src/lib/api.ts`（axios 实例 + 对话 / 历史 / 文件 / 助手封装），
  禁止组件内裸 `fetch` / 裸 axios（SSE 读取除外）。
* **SSE 必须用 `fetch` + `ReadableStream`**（POST 语义），解析逻辑集中在
  `src/lib/sse.ts`（帧解析纯函数）+ `src/lib/stream.ts`（读取与分发），禁止散落重复实现。
* 统一错误映射：HTTP 状态码 + SSE `error` 帧 `{status, code, message}` → 前端可读文案，
  集中 `src/lib/errors.ts` 一处维护。
* 请求体契约对齐后端：`{query, response_mode, conversation_id}`；`conversation_id` 空串 = 新建会话，
  续聊必带后端回传的会话 ID；会话 ID 取响应头 `X-Conversation-Id`（优先级）或响应体。
* **配置驱动**：API base URL、超时、功能开关、`query` 长度上限一律进环境变量（`VITE_*`），
  代码禁止硬编码 URL / 密钥 / 超时 / 阈值；环境文件统一收容于 `env/`（vite `envDir: ./env`），
  仓库只提交无密钥模板（`env/.env.example` 及 `env/.env.{development,test,production}`）。
* **Vite 装配**：Vite 原生支持 `envDir`（与 Nuxt 不同，无需 `--dotenv` 注入）；`VITE_*` 经
  `env/` 自动流入 `import.meta.env`，统一在 `src/env.ts` 收窄为类型化常量。dev 代理走
  `server.proxy`（目标读 `VITE_PROXY_TARGET`）。禁止改为在根目录明文提交 `.env`。

## 5. 流式（SSE）处理

* SSE 帧解析规则（后端契约，不可臆造）：
  * `data:` 行按空行分隔为帧；帧 JSON 的 `event` 字段判别类型。
  * `message` → 正文增量，追加到当前回复；`message_end` → 收尾帧，含 `metadata.assistant`，**流结束，无 `[DONE]`**。
  * `thinking_started` → 打开思考分区；`thinking_delta` → 思考增量（`content`）追加到思考分区；`thinking_ended` → 收起并显示耗时（`duration_ms`）。
  * 思考可多段（思考→工具→再思考）：所有思考追加同一分区，首个 `thinking_started` 打开、末次 `thinking_ended` 收起；思考不进正文。
  * `ping` → 心跳，忽略；`error` → 错误帧 `{status, code, message}`，展示错误态。
  * `response_mode=blocking` 不推思考帧，返回完整 JSON `{answer, metadata, conversation_id}`，思考不可见。
* 取消 / 停止：`AbortController` 关联 `fetch`，取消后同步复位 Zustand 流式状态，禁止残留半条消息态。
* 断线 / 超时：按 `VITE_SSE_TIMEOUT_MS` 兜底；流中断未到 `message_end` 视为异常，提示重试并保留已收内容。
* 消息去重 / 排序：以 `message_id` 标识当前消息，`seq` 仅用于开发调试，不参与 UI 排序。
* **turn 作废机制**：切换 / 新建会话时作废旧流 token，旧流残留帧与回调不再写 store（防幽灵增量）。
* **卸载清理（性能红线）**：`useChatStream` 所在组件卸载时必须 `abort()` 并 cancel / release
  ReadableStream 的 reader（见 `.claude/commands/performance.md` §3）。

## 6. 安全红线（不可逃逸）

* 模型输出 HTML 一律只经 **react-markdown** 渲染（默认跳过原始 HTML，`rehype-raw` 禁止开启）。
* **禁止** `dangerouslySetInnerHTML` 直接绑定未经 DOMPurify 清洗的内容；若存在该边界，必须
  `DOMPurify.sanitize` 后绑定。
* 文件预览 / 下载：`a[download]` 指向 `GET /api/v1/files/{file_id}/preview`（旧产物下载接口
  `/sessions/{sid}/artifacts/{aid}` 已移除）。后端以 `Content-Disposition: inline` 返回，前端加
  `download` 属性才触发下载；预览仅限图片缩略 / 新窗口打开，禁止将文件内容作为 HTML 内联渲染。
* 渲染标记语言（如 markdown 内嵌链接）注意 `javascript:` 等协议，由 DOMPurify 默认策略拦截，
  不得放开 `ALLOWED_URI_REGEXP` 之外的协议。

## 7. 组件规范

* 单文件组件 ≤ 300 行，职责单一；主编排组件（如 `ChatPage.tsx`，`App.tsx` 仅路由表）超行需 `// pragma: 简化 — 编排页`。
* 组件统一落位 `src/components/`（`ui/` 为 shadcn 拷入组件；其余按域分目录），禁止散落。
* 可复用逻辑抽 `src/hooks/`（React 生命周期相关）与 `src/lib/`（纯逻辑），禁止组件内复制粘贴逻辑。
* UI 一律 shadcn/ui + Tailwind；自定义视觉只做样式扩展（Tailwind 工具类 / CSS 变量），不改组件行为。
* 弹层 / 提示统一 **sonner**，禁止散落 `window.alert` / 自制 toast。

## 8. 性能红线（不可逃逸的高频路径）

针对 SSE 毫秒级增量追加，以下规则可判定，违反需 `// pragma: 简化` 标注原因：

1. **消息组件隔离**：`MessageBubble` 必须 `React.memo` 包裹，历史消息 props 引用不变即绝不重渲。
2. **流式渲染降载**：正在生成的单条消息，Markdown 视图采用 `useDeferredValue` + 节流（30–50ms）
   更新；`rehype-highlight` 代码高亮**仅在 `message_end` 后对最终文本执行**，增量期间走轻量渲染
   （纯文本 / 延迟高亮）。流式光标（`▍`）独立于重解析呈现。
3. **状态粒度**：组件只订阅所需切片（见第 3 节）；`activeMessages` 独立；禁止把整个 messages 数组
   暴露给无关组件。
4. **SSE 清理**：`useChatStream` 卸载清理必须 `abort()`；ReadableStream reader 必须 cancel / release；
   配合 turn 作废，杜绝后台幽灵请求写脏状态。
5. **版本兼容**：React 19 / Tailwind v4 / motion 的 peerDependencies 已在脚手架阶段验证；
   shadcn/ui 生成产物已确认 `cn()` 与 CSS 变量衔接正常。

详见 `.claude/commands/performance.md`（实现策略与样例）。

## 9. 设计原则（SOLID + CARP）

以下规则为可判定基线，违反需 `// pragma: 简化` 标注原因。

| # | 原则 | 可判定规则 |
|---|---|---|
| 1 | **SRP** 单一职责 | 函数 ≤ 30 行、参数 ≤ 5 个；主函数只做编排，细节下沉为私有子函数 |
| 2 | **OCP** 开闭 | 同一维度的分支超过 3 个 → 改用策略表 / 注册表 / 配置驱动；禁止无限延伸的 if-else 链 |
| 3 | **LSP** 里氏替换 | 重写方法 / 实现接口不收窄入参、不放宽返回类型、不新增父类未声明的异常 |
| 4 | **LoD** 迪米特 | 链式访问最多 2 跳；`a.b.c.d` 一律封装为方法暴露 |
| 5 | **ISP** 接口隔离 | 单个 `interface` / 类型方法数 ≤ 5；按调用方需求拆分，不定义大而全接口 |
| 6 | **DIP** 依赖倒置 | 组件 / hooks 只依赖注入的 store / 服务封装与抽象类型，禁止在组件内直接 `new` 底层工具类 |
| 7 | **CARP** 合成复用 | 继承深度 ≤ 2 层；为复用而继承 / mixins 一律改为组合 + props 注入 |

## 10. `.ai` 记忆维护

* `.ai/ARCHITECTURE.md`：架构快照 + 关键设计决策，代码结构变化后同步更新。
* `.ai/MODULE_MAP.md`：职责 → 文件路径速查表，新增 / 删除模块文件后同步更新。
* 一次性任务报告、进度记录不属于记忆，不写入 `.ai`。

## 11. 本地持久化

* 会话列表 / 消息历史均由**后端历史接口持有**（`GET /conversations`、`GET /conversations/{id}/messages`，
  契约见 `.claude/feature/API.md`）；后端为唯一事实源，前端**不做持久数据源**。
* **例外（显示级缓存）**：会话列表在 `src/stores/conversations.ts` 缓存到 localStorage
  `disf_conversations_cache`，仅用于刷新 / 重回对话页时免闪加载骨架（三个空白）的即时展示，
  每次 `loadList`/`reconcileList` 全量覆盖校准，登出 / 过期经 `replaceAll([])` 清空防跨账号泄漏；
  会话消息正文仍一律从后端拉取，不回写。
* 仅 UI 状态（如明暗主题 `disf_theme`）走 localStorage，`disf_` 前缀见 `src/lib/theme.ts`。
* 回合粒度持久化由后端完成：流式中断未到 `message_end` 不回写后端，刷新后该半条不恢复。
* 删除会话调后端 `DELETE /conversations/{id}`（软删除：`204`/`404` 均按已删除处理，
  其他错误保留条目），成功后本地移除。

## 12. 禁止扫描 / 读取路径

* 敏感文件：`.env`、`*.pem`、`*.key`
* 构建产物：`node_modules/`、`dist/`、`.nuxt/`、`.output/`、`coverage/`、`.vite/`、`__pycache__/`
* `.gitignore` 忽略的全部内容
* 历史参考：`.claude/feature/` —— 仅用户明确提及时才读取

## 13. 交付前自检清单

改动 TS / React 代码后，未全部通过不得交付：

- [ ] `pnpm typecheck`（`tsc --noEmit`）通过，无 `any`、无裸 `as` / 无依据 `!`
- [ ] `pnpm lint`（Biome，lint + format 单一规则源）通过
- [ ] 无未经 `DOMPurify` 清洗的 `dangerouslySetInnerHTML`（第 6 节）
- [ ] 无硬编码 URL / 超时 / 阈值 / 密钥（第 4 节）
- [ ] SSE 解析仅存在于 `src/lib/sse.ts` + `src/lib/stream.ts` 两处，无 `EventSource`
- [ ] 跨组件共享状态均走 Zustand，且订阅为粒度 selector（第 3、8 节）
- [ ] `MessageBubble` 已 `React.memo`；流式高亮仅在 `message_end` 后执行（第 8 节）
- [ ] `useChatStream` 卸载时已 `abort()`（第 8 节）
- [ ] 未引入技术栈表之外的库 / 依赖（第 1 节硬约束）
- [ ] 纯客户端 SPA 未被改动；`dist/` 未提交（第 1、12 节）
- [ ] 偏离设计原则（第 9 节）处均有 `// pragma: 简化 — <原因>`
- [ ] 未扫描 / 读取第 12 节禁止路径（`.env`、`node_modules/`、`.claude/feature/` 等）
- [ ] 代码结构变化时已更新 `.ai/ARCHITECTURE.md` 与 `.ai/MODULE_MAP.md`
