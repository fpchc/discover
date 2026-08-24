import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useChatStore } from './chat'

function freshChatStore(): ReturnType<typeof useChatStore> {
  setActivePinia(createPinia())
  return useChatStore()
}

describe('chat store', () => {
  beforeEach(() => {
    localStorage.clear()
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

  it('完成的对话落盘快照，新 store 实例可按会话恢复', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.appendDelta('answer')
    chat.setConversationId('cid-1')
    chat.completeAssistant({ total_tokens: 5 })

    const fresh = freshChatStore()
    fresh.loadConversation('cid-1')
    expect(fresh.messages).toHaveLength(2)
    expect(fresh.messages[1].content).toBe('answer')
    expect(fresh.messages[1].status).toBe('done')
    expect(fresh.conversationId).toBe('cid-1')
  })

  it('失败 / 流式中断消息不落盘', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.appendDelta('部分')
    chat.setConversationId('cid-2')
    chat.failAssistant('error')

    const fresh = freshChatStore()
    fresh.loadConversation('cid-2')
    expect(fresh.messages).toHaveLength(0)
  })

  it('reset 清空会话与消息，未删除快照', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.setConversationId('cid-1')
    chat.reset()
    expect(chat.messages).toHaveLength(0)
    expect(chat.conversationId).toBe('')
    expect(chat.isStreaming).toBe(false)

    const fresh = freshChatStore()
    fresh.loadConversation('cid-1')
    expect(fresh.messages).toHaveLength(0)
  })

  it('clearSnapshot 删除指定会话快照', () => {
    const chat = useChatStore()
    chat.beginTurn('hi')
    chat.appendDelta('a')
    chat.setConversationId('cid-3')
    chat.completeAssistant()
    chat.clearSnapshot('cid-3')

    const fresh = freshChatStore()
    fresh.loadConversation('cid-3')
    expect(fresh.messages).toHaveLength(0)
  })
})
