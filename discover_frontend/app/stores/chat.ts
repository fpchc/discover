import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatMessage, ConversationUsage, MessageStatus, UsageInfo } from '@/api/types'

function localId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * 对话状态（单一事实源）。流式增量只写这里，组件只做渲染。
 * 本层不做 HTTP / SSE；帧消费由 useChatStream 驱动，回调本 store。
 * 消息历史来自后端接口（API.md §1），本层不再落 localStorage 快照。
 */
export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const conversationId = ref<string>('')
  const isStreaming = ref<boolean>(false)
  /** 当前会话用量汇总（GET /conversations/{id}/usage；切换会话时由编排层写入） */
  const usageSummary = ref<ConversationUsage | null>(null)
  /** 历史消息加载中（切换会话时展示） */
  const loadingHistory = ref<boolean>(false)

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

  /** 思考开始：打开当前助手消息的思考分区（首个 thinking_started） */
  function startThinking(): void {
    const current = currentStreamingMessage()
    if (current !== undefined) current.thinkingStatus = 'thinking'
  }

  /** 思考增量：追加到思考分区（思考中状态保持展开；首个 thinking_delta 亦视为开始） */
  function appendThinking(delta: string): void {
    const current = currentStreamingMessage()
    if (current !== undefined) {
      current.thinking = (current.thinking ?? '') + delta
      current.thinkingStatus = 'thinking'
    }
  }

  /** 思考结束：折叠思考分区并记录耗时（thinking_ended.duration_ms） */
  function endThinking(durationMs: number): void {
    const current = currentStreamingMessage()
    if (current !== undefined) {
      current.thinkingStatus = 'done'
      current.thinkingDurationMs = durationMs
    }
  }

  function completeAssistant(usage?: UsageInfo): void {
    const current = currentStreamingMessage()
    if (current !== undefined) {
      current.status = 'done'
      current.usage = usage
    }
    isStreaming.value = false
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
      }
    }
    isStreaming.value = false
  }

  function setConversationId(id: string): void {
    conversationId.value = id
  }

  /** 整体替换消息列表（切换会话时由编排层写入后端历史）；替换即终止当前流式态 */
  function setMessages(list: ChatMessage[]): void {
    messages.value = list
    isStreaming.value = false
  }

  function setUsageSummary(usage: ConversationUsage | null): void {
    usageSummary.value = usage
  }

  function setLoadingHistory(value: boolean): void {
    loadingHistory.value = value
  }

  /** 新建会话 / 清空当前消息区 */
  function reset(): void {
    messages.value = []
    conversationId.value = ''
    isStreaming.value = false
    usageSummary.value = null
    loadingHistory.value = false
  }

  return {
    messages,
    conversationId,
    isStreaming,
    usageSummary,
    loadingHistory,
    beginTurn,
    beginRetryTurn,
    appendDelta,
    startThinking,
    appendThinking,
    endThinking,
    completeAssistant,
    failAssistant,
    abortTurn,
    setConversationId,
    setMessages,
    setUsageSummary,
    setLoadingHistory,
    reset,
  }
})
