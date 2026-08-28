import { create } from 'zustand'
import type { ChatMessage, MessageStatus } from '@/types'

/**
 * 对话状态（单一事实源，CLAUDE.md 第 3 节）。
 * - activeMessages：当前会话消息切片（流式增量只写这里，与 conversations.items 解耦）。
 * - 流式增量按「不可变更新」替换正在流式的那一条（历史消息对象引用保持不变，
 *   配合 MessageBubble 的 React.memo 跳过无关重渲，见 .claude/commands/performance.md）。
 * - 本层不做 HTTP / SSE；帧消费由 hooks/useChatStream 驱动，回调本 store。
 * - 消息历史来自后端接口（API.md §1），本层不再落 localStorage 快照。
 */
export interface ChatState {
  activeMessages: ChatMessage[]
  conversationId: string
  isStreaming: boolean
  /** 历史消息加载中（切换会话时展示） */
  loadingHistory: boolean
  beginTurn: (userText: string) => void
  beginRetryTurn: () => void
  appendDelta: (delta: string) => void
  startThinking: () => void
  appendThinking: (delta: string) => void
  endThinking: (durationMs: number) => void
  completeAssistant: () => void
  failAssistant: (message: string) => void
  abortTurn: () => void
  setConversationId: (id: string) => void
  setMessages: (list: ChatMessage[]) => void
  setLoadingHistory: (value: boolean) => void
  reset: () => void
}

function localId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * 查找正在流式的助手消息下标（自末尾向前）。
 * 返回 -1 表示不存在；此时原数组原样返回（set 无变化 → 不通知订阅者）。
 */
function updateStreamingMessage(
  messages: ChatMessage[],
  update: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  let index = -1
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i]
    if (message !== undefined && message.role === 'assistant' && message.status === 'streaming') {
      index = i
      break
    }
  }
  if (index === -1) return messages
  const current = messages[index]
  if (current === undefined) return messages
  return messages.slice(0, index).concat(update(current), messages.slice(index + 1))
}

export const useChatStore = create<ChatState>((set) => ({
  activeMessages: [],
  conversationId: '',
  isStreaming: false,
  loadingHistory: false,

  beginTurn: (userText) =>
    set((state) => ({
      activeMessages: state.activeMessages.concat([
        {
          id: localId('user'),
          role: 'user',
          content: userText,
          created_at: new Date().toISOString(),
          status: 'done',
        },
        {
          id: localId('assistant'),
          role: 'assistant',
          content: '',
          created_at: new Date().toISOString(),
          status: 'streaming',
        },
      ]),
      isStreaming: true,
    })),

  beginRetryTurn: () =>
    set((state) => {
      const list = state.activeMessages
      const last = list[list.length - 1]
      // 失败重试：移除上一条失败助手消息，重开一条流式助手消息
      const base = last !== undefined && last.role === 'assistant' ? list.slice(0, -1) : list
      return {
        activeMessages: base.concat([
          {
            id: localId('assistant'),
            role: 'assistant',
            content: '',
            created_at: new Date().toISOString(),
            status: 'streaming',
          },
        ]),
        isStreaming: true,
      }
    }),

  appendDelta: (delta) =>
    set((state) => ({
      activeMessages: updateStreamingMessage(state.activeMessages, (current) => ({
        ...current,
        content: current.content + delta,
      })),
    })),

  startThinking: () =>
    set((state) => ({
      activeMessages: updateStreamingMessage(state.activeMessages, (current) => ({
        ...current,
        thinkingStatus: 'thinking',
      })),
    })),

  appendThinking: (delta) =>
    set((state) => ({
      activeMessages: updateStreamingMessage(state.activeMessages, (current) => ({
        ...current,
        thinking: (current.thinking ?? '') + delta,
        thinkingStatus: 'thinking',
      })),
    })),

  endThinking: (durationMs) =>
    set((state) => ({
      activeMessages: updateStreamingMessage(state.activeMessages, (current) => ({
        ...current,
        thinkingStatus: 'done',
        thinkingDurationMs: durationMs,
      })),
    })),

  completeAssistant: () =>
    set((state) => ({
      activeMessages: updateStreamingMessage(state.activeMessages, (current) => ({
        ...current,
        status: 'done' satisfies MessageStatus,
      })),
      isStreaming: false,
    })),

  failAssistant: (message) =>
    set((state) => ({
      activeMessages: updateStreamingMessage(state.activeMessages, (current) => ({
        ...current,
        status: 'error' satisfies MessageStatus,
        errorMessage: message,
      })),
      isStreaming: false,
    })),

  abortTurn: () =>
    set((state) => {
      const list = state.activeMessages
      const last = list[list.length - 1]
      if (last === undefined || last.role !== 'assistant' || last.status !== 'streaming') {
        return state
      }
      // 用户停止生成：空内容移除该条，非空保留正文并标记完成
      const base = last.content.trim() === '' ? list.slice(0, -1) : list
      const activeMessages =
        last.content.trim() === ''
          ? base
          : base.slice(0, -1).concat({ ...last, status: 'done' as const })
      return { activeMessages, isStreaming: false }
    }),

  setConversationId: (id) => set({ conversationId: id }),

  /** 整体替换消息列表（切换会话时由编排层写入后端历史）；替换即终止当前流式态 */
  setMessages: (list) => set({ activeMessages: list, isStreaming: false }),

  setLoadingHistory: (value) => set({ loadingHistory: value }),

  /** 新建会话 / 清空当前消息区 */
  reset: () =>
    set({
      activeMessages: [],
      conversationId: '',
      isStreaming: false,
      loadingHistory: false,
    }),
}))
