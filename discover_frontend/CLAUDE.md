# CLAUDE.md — discover_frontend 全局红线约束

> 本文件是前端项目的全局硬约束，与后端 `discover_backend/CLAUDE.md` 同构：只写可判定的红线。
> 架构 / 目录结构 / 模块职责等结构性说明放 `.claude/commands/architecture.md`；架构快照与模块映射存 `.ai/*.md`。
> 详细需求与交互细节见 `.claude/feature/REQUIREMENTS.md`。
> **逃逸机制**：本文件所有规则在严格遵循会导致过度设计时，允许实用主义简化，但必须在代码处标注
> `// pragma: 简化 — <原因>`。无标注的偏离视为违规。

## 0. 项目定位

* 框架层采用 **Nuxt 4（SPA 模式 `ssr: false`）**：Nuxt 承担构建 / dev server / 路由 / 模块装配唯一入口，
  渲染始终发生在浏览器端，部署保持 nginx 静态托管（见第 1、4 节）。
* 后端为 `discover_backend`（多智能体承载平台），对话走 `POST /api/v1/chat-messages`。
* 前端**只消费已有 API**，不新增后端接口；会话列表 / 消息历史 / 用量由后端历史接口提供
  （`GET /conversations`、`GET /conversations/{id}/messages`、`GET /conversations/{id}/usage`），
  文件走 `GET|POST /files/upload` 与 `GET /files/{id}/preview`；前端不做本地持久化（见第 10 节）。

## 1. 技术栈（固定，不可替换，不可新增未列出的同类库）

| 技术 | 约束 |
|---|---|
| **Vue 3.5+** | `<script setup lang="ts">` + Composition API，禁止 Options API 混用 |
| **TypeScript（strict）** | 见第 2 节；`nuxt typecheck`（基于 vue-tsc）作为类型检查基线 |
| **Nuxt 4** | 构建 / dev server / 路由 / 模块装配唯一入口（底层基于 Vite，`vite:` 配置经 `nuxt.config.ts` 透传）；**`ssr: false`（SPA 模式）固定**，渲染始终在浏览器端 |
| **Nitro** | Nuxt 内置服务引擎；本项目 SPA 模式下仅承担 dev 代理（`nitro.devProxy`）与静态产物（`.output/`） |
| **Element Plus** | 全部 UI 组件来源（按钮、输入框、对话框、空态等）；经 **`@element-plus/nuxt`** 模块装配（SPA 下按需）；禁止用私有样式重造既有组件 |
| **Pinia** | 跨组件共享状态唯一通道（第 3 节）；经 **`@pinia/nuxt`** 模块装配 |
| **Nuxt 文件路由** | `app/pages/` 目录约定（底层基于 vue-router）；**禁止手写 `createRouter` / 路由表** |
| **Axios** | 普通 HTTP（blocking 模式）唯一出口，统一实例在 `app/api/client.ts` |
| **fetch + ReadableStream** | SSE 唯一实现方式。`POST` 无法用 `EventSource`，禁止 `EventSource` |
| **markdown-it** | Markdown 渲染唯一实现，配 `highlight.js` 代码高亮 |
| **DOMPurify** | HTML 清洗唯一实现，渲染红线见第 6 节 |
| **Biome** | lint / format 单一规则源（Rust 原生，替代 ESLint + Prettier） |
| **Vitest + @vue/test-utils** | 单测框架（SSE 解析、历史映射、store 等纯逻辑） |

以下两条为**可判定硬约束，逃逸机制（`// pragma`）不适用**：
* **`ssr: false` 固定**。切换 SSR 属架构变更，必须先评估第 5 节 SSE / 第 6 节 DOMPurify /
  `navigator` / `window` 守卫，不得以 `// pragma` 轻率绕过。
* 未列入本表的同类库（含 Nuxt 模块）一律不得新增；AppIcon 保持手写 SVG，不引入
  `@element-plus/icons-vue`。

包管理器 `pnpm`；Node `>= 20`（建议 22 LTS）。未列出的同类库（状态管理、HTTP、Markdown、UI、Lint/Format、测试框架）一律不得新增。

## 2. 语言与类型

* **全量显式标注**：所有函数、props、emits、store state/getter/action 的入参与返回必须显式类型；
  禁止依赖 IDE / 默认值推断。
* **业务代码显式 import**：允许 Nuxt 模块的自动导入（`@element-plus/nuxt` 的组件 / 样式 / 方法），
  但业务代码一律显式 import，禁止依赖 Nuxt 对 `composables/` / `utils/` 名称的隐式自动导入绑定，避免歧义。
* **禁止 `any` 规避检查**：与后端契约对齐的类型集中定义于 `app/api/types.ts`（映射后端 pydantic 模型），
  禁止在组件内散落重复定义。仅在与无类型第三方库的边界允许 `any`，需 `// pragma: 简化 — <原因>`。
* **禁止裸 `as` 断言**绕过检查：仅 `JSON.parse` 等运行时边界允许，且必须带类型收窄说明注释。
* **`!` 非空断言**：仅当在运行时用上游逻辑保证非空时允许，并注释依据；禁止用来掩盖未初始化缺陷。
* **接口用 `type`**：跨模块契约统一 `interface`（对象形状）与 `type`（联合 / 工具类型），对齐后端 pydantic 判别联合。

## 3. 状态与数据流

* 跨组件共享状态一律 Pinia store（`app/stores/conversations.ts`、`app/stores/chat.ts`），由
  `@pinia/nuxt` 模块装配；禁止组件间互引状态 / 全局事件总线。
* **props 单向数据流**：子组件通过 `defineProps` 收数据、`defineEmits` 上报事件，禁止直接改写 props。
* 流式对话过程中，消息增量必须写入 Pinia（单一事实源），组件只做渲染，禁止组件持有对话副本。
* 组件为纯展示时用 `v-model` 由父组件托管；禁止在子组件内 `watch` 后修改共享状态造成环路。
* **SPA 无 SSR 水合**：Pinia 状态仅存于客户端；禁止引入 `useAsyncData` / `useFetch` 做数据预取，
  数据拉取保持现有编排（`onMounted` + `useChatStream`）不变。

## 4. API 与网络

* 所有 HTTP 出口统一走 `app/api/`（`client.ts` 的 axios 实例 + `chat.ts` 的对话封装），禁止组件内裸 `fetch` / 裸 axios。
* **SSE 必须用 `fetch` + `ReadableStream`**（POST 语义），解析逻辑集中在 `app/composables/useChatStream.ts`，禁止散落重复实现。
* 统一错误映射：HTTP 状态码 + SSE `error` 帧 `{status, code, message}` → 前端可读文案，集中一处维护。
* 请求体契约对齐后端：`{query, response_mode, conversation_id}`；`conversation_id` 空串 = 新建会话，
  续聊必带后端回传的会话 ID；会话 ID 取响应头 `X-Conversation-Id`（优先级）或响应体。
* **配置驱动**：API base URL、超时、功能开关、`query` 长度上限一律进环境变量（`VITE_*`），
  代码禁止硬编码 URL / 密钥 / 超时 / 阈值；环境文件统一收容于 `env/`（vite `envDir: ./env`），
  仓库只提交无密钥模板（`env/.env.example` 及 `env/.env.development` / `.env.test` / `.env.production`）。
* **Nuxt 装配**：Nuxt 不采纳 `vite.envDir`（实测未将 `env/` 注入 `import.meta.env`）；`env/` 的环境由各
  命令 `--dotenv ./env/.env.{development,test,production}` 注入 process.env 后流入 `import.meta.env`
  （package.json script 已内置，进程内已有同名变量优先）；dev 代理走 `nitro.devProxy`
  （目标读 `VITE_PROXY_TARGET`），替代 `vite.config.ts` 的 `server.proxy`。
  仍保持配置驱动、无密钥模板提交；禁止改为在根目录明文提交 `.env`。

## 5. 流式（SSE）处理

* SSE 帧解析规则（后端契约，不可臆造）：
  * `data:` 行按空行分隔为帧；帧 JSON 的 `event` 字段判别类型。
  * `message` → 正文增量，追加到当前回复；`message_end` → 收尾帧，含 `metadata.usage`，**流结束，无 `[DONE]`**。
  * `thinking_started` → 打开思考分区；`thinking_delta` → 思考增量（`content`）追加到思考分区；`thinking_ended` → 收起并显示耗时（`duration_ms`）。
  * 思考可多段（思考→工具→再思考）：所有思考追加同一分区，首个 `thinking_started` 打开、末次 `thinking_ended` 收起；思考不进正文。
  * `ping` → 心跳，忽略；`error` → 错误帧 `{status, code, message}`，展示错误态。
  * `response_mode=blocking` 不推思考帧，返回完整 JSON `{answer, metadata, conversation_id}`，思考不可见。
* 取消 / 停止：`AbortController` 关联 `fetch`，取消后同步复位 Pinia 中的流式状态，禁止残留半条消息态。
* 断线 / 超时：按 `VITE_SSE_TIMEOUT_MS` 兜底；流中断未到 `message_end` 视为异常，提示重试并保留已收内容。
* 消息去重 / 排序：以 `message_id` 标识当前消息，`seq`（后端内部事件序号）仅用于开发调试，不参与 UI 排序。
* **客户端作用域**：SSE 与全部浏览器 API（`fetch` + `ReadableStream`、`AbortController`、`navigator`、
  `window`）仅允许在客户端作用域执行；当前 `ssr: false` 天然满足，未来切换 SSR 时以此为准绳（见第 1 节硬约束）。

## 6. 安全红线（不可逃逸）

* 任何进入 DOM 的模型输出 HTML（Markdown 渲染结果、事件 `result_summary` 等）**必须经 `DOMPurify.sanitize`**。
* **禁止** `v-html` 直接绑定未经清洗的内容。
* 文件预览 / 下载：`a[download]` 指向 `GET /api/v1/files/{file_id}/preview`（旧产物下载接口
  `/sessions/{sid}/artifacts/{aid}` 已移除）。后端以 `Content-Disposition: inline` 返回，前端加
  `download` 属性才触发下载；预览仅限图片缩略 / 新窗口打开，禁止将文件内容作为 HTML 内联渲染。
* 渲染标记语言（如 markdown 内嵌链接）注意 `javascript:` 等协议，由 DOMPurify 默认策略拦截，不得放开 `ALLOWED_URI_REGEXP` 之外的协议。

## 7. 组件规范

* 单文件组件 ≤ 300 行，职责单一；主编排组件（如 `ChatView.vue`）超行需 `// pragma: 简化 — 编排页`。
* 组件统一落位 `app/components/`（`layout/` / `chat/` / `common/`），遵循 Nuxt 4 目录约定。
* 可复用逻辑抽 `app/composables/`（`useChatStream` / `useMarkdown`），禁止组件内复制粘贴逻辑。
* UI 一律 Element Plus；自定义视觉只做样式扩展（CSS 变量 / SCSS），不改组件行为。
* 弹层 / 提示统一 `ElMessage` / `ElMessageBox`，禁止散落 `window.alert`。

## 8. 设计原则（SOLID + CARP）

以下规则为可判定基线，违反需 `// pragma: 简化` 标注原因。

| # | 原则 | 可判定规则 |
|---|---|---|
| 1 | **SRP** 单一职责 | 函数 ≤ 30 行、参数 ≤ 5 个；主函数只做编排，细节下沉为私有子函数 |
| 2 | **OCP** 开闭 | 同一维度的分支超过 3 个 → 改用策略表 / 注册表 / 配置驱动；禁止无限延伸的 if-else 链 |
| 3 | **LSP** 里氏替换 | 重写方法 / 实现接口不收窄入参、不放宽返回类型、不新增父类未声明的异常 |
| 4 | **LoD** 迪米特 | 链式访问最多 2 跳；`a.b.c.d` 一律封装为方法暴露 |
| 5 | **ISP** 接口隔离 | 单个 `interface` / 抽象类方法数 ≤ 5；按调用方需求拆分，不定义大而全接口 |
| 6 | **DIP** 依赖倒置 | 组件 / composable 只依赖注入的 store / 服务封装与抽象类型，禁止在组件内直接 `new` 底层工具类 |
| 7 | **CARP** 合成复用 | 继承深度 ≤ 2 层；为复用而继承 / mixins 一律改为组合 + props / emits 注入 |

## 9. `.ai` 记忆维护

* `.ai/ARCHITECTURE.md`：架构快照 + 关键设计决策，代码结构变化后同步更新。
* `.ai/MODULE_MAP.md`：职责 → 文件路径速查表，新增 / 删除模块文件后同步更新。
* 一次性任务报告、进度记录不属于记忆，不写入 `.ai`。

## 10. 本地持久化

* 会话列表 / 消息历史 / 用量汇总**均由后端历史接口持有**（`GET /conversations`、
  `GET /conversations/{id}/messages`、`GET /conversations/{id}/usage`，契约见 `.claude/feature/API.md`）；
  前端不做会话数据本地持久化（会话列表唯一事实源在后端）。
* 仅 UI 状态（如明暗主题 `disf_theme`）走 localStorage，`disf_` 前缀见 `useTheme`。
* 回合粒度持久化由后端完成：流式中断未到 `message_end` 不回写后端，刷新后该半条不恢复。
* 删除会话为前端本地移除（后端无删除接口），刷新后后端会再次带回。

## 11. 禁止扫描 / 读取路径

* 敏感文件：`.env`、`*.pem`、`*.key`
* 构建产物：`node_modules/`、`dist/`、`.nuxt/`、`.output/`、`coverage/`、`.vite/`、`__pycache__/`
* `.gitignore` 忽略的全部内容
* 历史参考：`.claude/feature/` —— 仅用户明确提及时才读取

## 12. 交付前自检清单

改动 TS / Vue 代码后，未全部通过不得交付：

- [ ] `pnpm typecheck`（`nuxt typecheck`，基于 vue-tsc）通过，无 `any`、无裸 `as` / 无依据 `!`
- [ ] `pnpm lint`（Biome，lint + format 单一规则源）通过
- [ ] 无未经 `DOMPurify` 清洗的 `v-html`（第 6 节）
- [ ] 无硬编码 URL / 超时 / 阈值 / 密钥（第 4 节）
- [ ] SSE 解析仅存在于 `app/composables/useChatStream.ts` 一处
- [ ] 跨组件共享状态均走 Pinia，无组件互改状态
- [ ] 无手写 `createRouter` / 路由表（全部走 `app/pages/` 文件路由，第 1 节）
- [ ] 未引入技术栈表之外的库 / Nuxt 模块（第 1 节硬约束）
- [ ] `ssr: false` 未被改动；`.nuxt/`、`.output/` 未提交（第 1、11 节）
- [ ] 偏离设计原则（第 8 节）处均有 `// pragma: 简化 — <原因>`
- [ ] 未扫描 / 读取第 11 节禁止路径（`.env`、`node_modules/`、`.claude/feature/` 等）
- [ ] 代码结构变化时已更新 `.ai/ARCHITECTURE.md` 与 `.ai/MODULE_MAP.md`
