import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import type { ChatMessage } from '@/api/types'
import { useChatStore } from './chat'

function userMessage(id: string): ChatMessage {
  return {
    id,
    role: 'user',
    content: `内容-${id}`,
    created_at: '2026-08-26T11:00:00',
    status: 'done',
  }
}

describe('chat store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('beginTurn 追加用户消息与流式助手消息', () => {
    const chat = useChatStore()
    chat.beginTurn('你好')
    expect(chat.messages).toHaveLength(2)
    expect(chat.messages[0]).toMatchObject({ role: 'user', content: '你好', status: 'done' })
    expect(chat.messages[1]).toMatchObject({ role: 'assistant', status: 'streaming' })
    expect(chat.isStreaming).toBe(true)
  })

  it('appendDelta 累积到当前助手消息', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.appendDelta('你')
    chat.appendDelta('好')
    expect(chat.messages[1].content).toBe('你好')
  })

  it('completeAssistant 置为 done 并写入 usage', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.appendDelta('ok')
    chat.setConversationId('cid-1')
    chat.completeAssistant({ total_tokens: 10, prompt_tokens: 4, completion_tokens: 6 })
    const last = chat.messages[1]
    expect(last.status).toBe('done')
    expect(last.usage?.total_tokens).toBe(10)
    expect(chat.isStreaming).toBe(false)
  })

  it('failAssistant 置错误态并保留正文', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.appendDelta('部分内容')
    chat.failAssistant('连接中断')
    const last = chat.messages[1]
    expect(last.status).toBe('error')
    expect(last.errorMessage).toBe('连接中断')
    expect(last.content).toBe('部分内容')
    expect(chat.isStreaming).toBe(false)
  })

  it('abortTurn 空内容移除助手消息，非空保留为 done', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.abortTurn()
    expect(chat.messages).toHaveLength(1)
    expect(chat.isStreaming).toBe(false)

    chat.beginTurn('hi2')
    chat.appendDelta('部分')
    chat.abortTurn()
    const last = chat.messages[chat.messages.length - 1]
    expect(last.status).toBe('done')
    expect(last.content).toBe('部分')
  })

  it('startThinking / appendThinking / endThinking 管理思考分区', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.startThinking()
    expect(chat.messages[1].thinkingStatus).toBe('thinking')
    chat.appendThinking('先分析产业链')
    chat.appendThinking('再圈定候选客户')
    expect(chat.messages[1].thinking).toBe('先分析产业链再圈定候选客户')
    chat.endThinking(8123)
    expect(chat.messages[1].thinkingStatus).toBe('done')
    expect(chat.messages[1].thinkingDurationMs).toBe(8123)
  })

  it('多段思考追加到同一思考分区，末次结束记录耗时', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.startThinking()
    chat.appendThinking('第一段推理')
    chat.endThinking(1000)
    chat.startThinking()
    chat.appendThinking('第二段推理')
    chat.endThinking(2000)
    const last = chat.messages[1]
    expect(last.thinking).toBe('第一段推理第二段推理')
    expect(last.thinkingStatus).toBe('done')
    expect(last.thinkingDurationMs).toBe(2000)
  })

  it('beginRetryTurn 移除上一条失败助手消息', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.failAssistant('boom')
    expect(chat.messages).toHaveLength(2)
    chat.beginRetryTurn()
    expect(chat.messages).toHaveLength(2)
    expect(chat.messages[1].status).toBe('streaming')
    expect(chat.isStreaming).toBe(true)
  })

  it('setMessages 整体替换消息列表（后端历史写入）', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.setMessages([userMessage('m1'), userMessage('m2')])
    expect(chat.messages).toHaveLength(2)
    expect(chat.messages[0].id).toBe('m1')
    // 历史写入后非流式态
    expect(chat.isStreaming).toBe(false)
  })

  it('setUsageSummary / setLoadingHistory 状态写入', () => {
    const chat = useChatStore()
    chat.setLoadingHistory(true)
    chat.setUsageSummary({
      message_count: 5,
      prompt_tokens: 600,
      completion_tokens: 400,
      total_tokens: 1000,
      cached_read_tokens: 200,
      cached_write_tokens: 100,
    })
    expect(chat.loadingHistory).toBe(true)
    expect(chat.usageSummary?.message_count).toBe(5)
    expect(chat.usageSummary?.total_tokens).toBe(1000)
  })

  it('reset 清空消息 / 会话 / 用量 / 加载态', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.setConversationId('cid-1')
    chat.setLoadingHistory(true)
    chat.setUsageSummary({
      message_count: 1,
      prompt_tokens: 1,
      completion_tokens: 1,
      total_tokens: 2,
      cached_read_tokens: 0,
      cached_write_tokens: 0,
    })
    chat.reset()
    expect(chat.messages).toHaveLength(0)
    expect(chat.conversationId).toBe('')
    expect(chat.isStreaming).toBe(false)
    expect(chat.usageSummary).toBeNull()
    expect(chat.loadingHistory).toBe(false)
  })
})
