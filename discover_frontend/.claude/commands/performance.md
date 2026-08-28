# 性能与状态粒度红线（SSE 高频路径）

## 适用场景 / 何时触发

- 编写 / 修改任何参与 SSE 流式渲染的组件、hooks、store 时
- 排查流式对话卡顿、CPU 占满、历史消息无故重渲、侧栏闪烁时
- 脚手架阶段版本选型与兼容性核对时

> 本文是 `CLAUDE.md` 第 8 节的实现策略展开，规则与第 8 节同源。**四类红线均不可逃逸
> （违反需 `// pragma: 简化` 标注原因）**。后端契约见 `.claude/feature/API.md`。

---

## 1. 消息组件隔离（`React.memo`）

SSE `message` 帧以毫秒级到达，`activeMessages` 数组每次追加都是新引用。若 `MessageBubble`
不隔离，整条消息流会随每一次 delta 全量重渲。

**硬规则**：

- `MessageBubble` 必须 `export const MessageBubble = memo(MessageBubbleInner)` 包裹。
- 对比函数默认浅比较 props：`message` 对象引用不变即不重渲。**不要在父组件渲染期给
  `message` 建新对象**（如 `{...m, x}` 拼到数组里会破坏 memo）。
- 事件回调（onRetry 等）用 `useCallback` 稳定引用；父级列表 map 时避免内联箭头函数。
- 流式期间只有「当前正在流式的那一条」的 `message` 引用变化，历史消息引用不变 → 天然跳过。

## 2. 流式 Markdown 渲染降载

react-markdown 每次 props 变化都会重新解析 AST + remark 插件处理，且 rehype-highlight 对
长代码块高亮是重活。SSE 逐字符追加会让它以毫秒级频率全量重跑——这是流式卡顿的头号来源。

**硬规则**：

- **流式期间用轻量视图**：正在生成（`status === 'streaming'`）的消息，不直接渲染完整
  `Markdown` 高亮版；渲染走以下任一策略：
  - 纯文本渲染（`white-space: pre-wrap`）+ 流式光标 `▍`（独立呈现），`message_end` 后切换到
    `Markdown` 高亮版；或
  - `useDeferredValue(content)` + 节流（**30–50ms**）合并增量，延迟渲染 `Markdown`。
- **高亮仅在收尾执行**：`rehype-highlight` 只在 `status === 'done'`（`message_end` 已到）时启用；
  流式期间不跑 highlight。
- 两种策略可组合：流式期 = 节流后的 deferred 轻渲染（无高亮），收尾 = 一次性完整高亮渲染。
- 实现要点：
  - 节流用 `useRef` 计时器（`setTimeout` 30–50ms 合并 pending 文本），卸载时 `clearTimeout`。
  - `useDeferredValue` 让出主线程，输入（delta）优先、渲染（Markdown）延后。
  - 流式光标 `▍`、打字三点动画与 Markdown 解析解耦，各自独立渲染。

## 3. 状态粒度（Zustand）

**硬规则**：

- **Active Chat 与 History 分离**：`chat` store 的 `activeMessages: ChatMessage[]` 是当前会话的
  独立切片；`conversations` store 的 `items` 是历史列表。流式增量只写 `activeMessages`，
  绝不触碰 `conversations.items`。
- **粒度订阅**：组件用 selector 只订阅所需切片，禁止整体订阅 store：
  - 侧栏只订阅 `useConversationsStore(s => s.items)`、`s.loading`、`useAssistantsStore(s => s.selectedId)`；
    **禁止订阅 `activeMessages`**。
  - 消息流容器订阅 `useChatStore(s => s.activeMessages)`；输入框订阅 `s.isStreaming`、`s.conversationId`。
- **禁止**在组件内把整个 store 对象当 props 传（`store.items` 引用随任何切片变化而变，
  会拖垮 memo / 触发无关重渲）。
- 新建会话 / 切换会话：`reset()` 只清 `activeMessages` 与 `conversationId`，不影响历史列表的
  乐观条目（由 `openConversation` / `loadList` 各自负责）。

## 4. SSE 卸载清理（AbortController + reader）

用户流式中快速切换会话、或组件卸载时，ReadableStream 必须被正确终止，否则后台幽灵请求
继续消费带宽、回调写脏状态。

**硬规则**：

- `useChatStream` 的 `AbortController` 生命周期：
  - 挂载 / 每次 turn 创建新 `controller`；
  - `useEffect` cleanup（卸载）+ 切换会话 / 新建会话 → 调 `abort()`；
  - `abort()` 后同步复位 `chat` 的流式状态（`isStreaming=false`），不留半条消息态。
- ReadableStream：`readChatStream` 的 `reader` 在 `finally` 中 `releaseLock()`；响应取消时
  `response.body.cancel()` 由 `abort()` 连带触发，不额外泄漏。
- **turn 作废机制**：每次 turn 递增 token，切换 / 新建会话后旧流残留帧与回调因 token 不匹配
  直接丢弃（`isCurrent()` 判断），从根上防幽灵增量写库。
- 节流计时器 / `matchMedia` 监听（`useTheme`）/ `online/offline` 监听（`useNetworkStatus`）均须
  在 cleanup 移除。

## 5. 版本兼容（脚手架阶段核对）

| 关注点 | 核对项 | 结论 |
|---|---|---|
| React 19 + 生态 peerDependencies | `pnpm install` 无 peer 冲突报错；Radix / sonner / motion / react-markdown 均声明支持 React 19 | 安装期验证 |
| Tailwind v4（无 `tailwind.config.js`） | `@import "tailwindcss"` + `@theme` 生效；`@custom-variant dark` 明暗切换正常 | dev server 验证 |
| shadcn/ui + Tailwind v4 | `shadcn init` 生成 `src/components/ui/` 与 `src/lib/utils.ts`；`cn()` 用 `clsx` + `tailwind-merge`；CSS 变量 → Tailwind token 映射（`@theme inline`）衔接正常 | 脚手架即验证 |
| motion + React 19 | 组件内 `motion.div` 类型通过 `tsc --noEmit` | typecheck 验证 |

> 若任一核对项失败：**优先升级 / 替换对应库版本**，不得降级规避（降级会拖入旧栈技术债）。
