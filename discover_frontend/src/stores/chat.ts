import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatMessage, MessageStatus, UsageInfo } from '@/api/types'
import { loadFromStorage, removeFromStorage, saveToStorage } from '@/utils/persist'

const SNAPSHOT_PREFIX = 'snap_'

function snapshotKey(conversationId: string): string {
  return `${SNAPSHOT_PREFIX}${conversationId}`
}

function localId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * 对话状态（单一事实源）。流式增量只写这里，组件只做渲染。
 * 本层不做 HTTP / SSE；帧消费由 useChatStream 驱动，回调本 store。
 *
 * 会话消息快照：仅在消息完成（message_end / 停止后保留正文）时落盘，流式中断不落盘
 * （CLAUDE.md 第 10 节）；刷新后按会话恢复。
 */
export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const conversationId = ref<string>('')
  const isStreaming = ref<boolean>(false)

  function pushAssistantMessage(status: MessageStatus = 'streaming'): void {
    messages.value.push({
      id: localId('assistant'),
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      status,
    })
  }

  /** 新回合：追加用户消息 + 流式助手消息 */
  function beginTurn(userText: string): void {
    messages.value.push({
      id: localId('user'),
      role: 'user',
      content: userText,
      created_at: new Date().toISOString(),
      status: 'done',
    })
    pushAssistantMessage()
    isStreaming.value = true
  }

  /** 失败重试：移除上一条失败助手消息，重开一条流式助手消息 */
  function beginRetryTurn(): void {
    const last = messages.value[messages.value.length - 1]
    if (last !== undefined && last.role === 'assistant') {
      messages.value.pop()
    }
    pushAssistantMessage()
    isStreaming.value = true
  }

  function currentStreamingMessage(): ChatMessage | undefined {
    const last = messages.value[messages.value.length - 1]
    if (last !== undefined && last.role === 'assistant' && last.status === 'streaming') {
      return last
    }
    return undefined
  }

  function appendDelta(delta: string): void {
    const current = currentStreamingMessage()
    if (current !== undefined) current.content += delta
  }

  function completeAssistant(usage?: UsageInfo): void {
    const current = currentStreamingMessage()
    if (current !== undefined) {
      current.status = 'done'
      current.usage = usage
    }
    isStreaming.value = false
    saveSnapshot()
  }

  function failAssistant(message: string): void {
    const current = currentStreamingMessage()
    if (current !== undefined) {
      current.status = 'error'
      current.errorMessage = message
    }
    isStreaming.value = false
  }

  /** 用户停止生成：空内容移除该条，非空保留正文并标记完成（F5） */
  function abortTurn(): void {
    const current = currentStreamingMessage()
    if (current !== undefined) {
      if (current.content.trim() === '') {
        messages.value.pop()
      } else {
        current.status = 'done'
        saveSnapshot()
      }
    }
    isStreaming.value = false
  }

  function setConversationId(id: string): void {
    conversationId.value = id
  }

  /** 新建会话 / 清空当前消息区 */
  function reset(): void {
    messages.value = []
    conversationId.value = ''
    isStreaming.value = false
  }

  /** 切换会话：按本地快照恢复已完成消息（无快照则空会话） */
  function loadConversation(id: string): void {
    conversationId.value = id
    messages.value = loadFromStorage<ChatMessage[]>(snapshotKey(id), [])
    isStreaming.value = false
  }

  /** 仅将已完成消息落盘为会话快照 */
  function saveSnapshot(): void {
    if (conversationId.value === '') return
    const done = messages.value.filter((message) => message.status === 'done')
    saveToStorage(snapshotKey(conversationId.value), done)
  }

  function clearSnapshot(conversationIdToClear: string): void {
    removeFromStorage(snapshotKey(conversationIdToClear))
  }

  return {
    messages,
    conversationId,
    isStreaming,
    beginTurn,
    beginRetryTurn,
    appendDelta,
    completeAssistant,
    failAssistant,
    abortTurn,
    setConversationId,
    reset,
    loadConversation,
    saveSnapshot,
    clearSnapshot,
  }
})
