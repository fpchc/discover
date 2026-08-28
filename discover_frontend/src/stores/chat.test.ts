import { beforeEach, describe, expect, it } from 'vitest'
import { useChatStore } from '@/stores/chat'
import type { ChatMessage } from '@/types'

const nextTick = (): Promise<void> => Promise.resolve()

beforeEach(() => {
  useChatStore.setState({
    activeMessages: [],
    conversationId: '',
    isStreaming: false,
    loadingHistory: false,
  })
})

describe('beginTurn', () => {
  it('追加用户消息 + 流式助手消息，进入流式态', () => {
    useChatStore.getState().beginTurn('你好')
    const state = useChatStore.getState()
    expect(state.isStreaming).toBe(true)
    expect(state.activeMessages).toHaveLength(2)
    expect(state.activeMessages[0]).toMatchObject({ role: 'user', content: '你好', status: 'done' })
    expect(state.activeMessages[1]).toMatchObject({
      role: 'assistant',
      content: '',
      status: 'streaming',
    })
  })
})

describe('appendDelta（不可变更新 + memo 稳定性）', () => {
  it('只替换正在流式的消息对象，历史消息引用保持不变', async () => {
    useChatStore.getState().beginTurn('问')
    const before = useChatStore.getState().activeMessages
    const historyUser = before[0] as ChatMessage

    useChatStore.getState().appendDelta('第')
    useChatStore.getState().appendDelta('一段')

    const after = useChatStore.getState().activeMessages
    // 用户消息对象引用不变（memo 可跳过重渲）
    expect(after[0]).toBe(historyUser)
    // 助手消息引用变化且内容累积
    expect(after[1]).not.toBe(before[1])
    expect(after[1]?.content).toBe('第一段')
    await nextTick()
  })
})

describe('思考分区', () => {
  it('start → delta → end 完整链路', () => {
    useChatStore.getState().beginTurn('推理')
    const { startThinking, appendThinking, endThinking } = useChatStore.getState()

    startThinking()
    let streaming = useChatStore.getState().activeMessages[1]
    expect(streaming?.thinkingStatus).toBe('thinking')

    appendThinking('让我想')
    appendThinking('想')
    streaming = useChatStore.getState().activeMessages[1]
    expect(streaming?.thinking).toBe('让我想想')
    expect(streaming?.thinkingStatus).toBe('thinking')

    endThinking(2300)
    streaming = useChatStore.getState().activeMessages[1]
    expect(streaming?.thinkingStatus).toBe('done')
    expect(streaming?.thinkingDurationMs).toBe(2300)
  })
})

describe('completeAssistant / failAssistant', () => {
  it('completeAssistant 标记完成并退出流式态', () => {
    useChatStore.getState().beginTurn('hi')
    useChatStore.getState().appendDelta('hello')
    useChatStore.getState().completeAssistant()
    const last = useChatStore.getState().activeMessages[1]
    expect(last?.status).toBe('done')
    expect(useChatStore.getState().isStreaming).toBe(false)
  })

  it('failAssistant 标记错误并带文案', () => {
    useChatStore.getState().beginTurn('hi')
    useChatStore.getState().failAssistant('连接中断')
    const last = useChatStore.getState().activeMessages[1]
    expect(last?.status).toBe('error')
    expect(last?.errorMessage).toBe('连接中断')
    expect(useChatStore.getState().isStreaming).toBe(false)
  })
})

describe('abortTurn（停止生成）', () => {
  it('空内容 → 移除该半条消息，不留空气泡', () => {
    useChatStore.getState().beginTurn('hi')
    useChatStore.getState().abortTurn()
    const state = useChatStore.getState()
    expect(state.activeMessages).toHaveLength(1)
    expect(state.activeMessages[0]?.role).toBe('user')
    expect(state.isStreaming).toBe(false)
  })

  it('非空内容 → 保留正文并标记完成', () => {
    useChatStore.getState().beginTurn('hi')
    useChatStore.getState().appendDelta('部分内容')
    useChatStore.getState().abortTurn()
    const last = useChatStore.getState().activeMessages[1]
    expect(last?.status).toBe('done')
    expect(last?.content).toBe('部分内容')
  })
})

describe('beginRetryTurn（失败重试）', () => {
  it('移除上一条失败助手消息，重开流式助手消息', () => {
    useChatStore.getState().beginTurn('hi')
    useChatStore.getState().failAssistant('超时')
    useChatStore.getState().beginRetryTurn()
    const state = useChatStore.getState()
    expect(state.activeMessages).toHaveLength(2)
    expect(state.activeMessages[1]).toMatchObject({
      role: 'assistant',
      content: '',
      status: 'streaming',
    })
    expect(state.isStreaming).toBe(true)
  })
})

describe('setMessages / setConversationId / setLoadingHistory / reset', () => {
  it('setMessages 整体替换并退出流式态', () => {
    useChatStore.getState().beginTurn('hi')
    useChatStore.getState().setMessages([
      {
        id: 'h1',
        role: 'user',
        content: '历史',
        created_at: '2026-01-01T00:00:00Z',
        status: 'done',
      },
    ])
    const state = useChatStore.getState()
    expect(state.activeMessages).toHaveLength(1)
    expect(state.activeMessages[0]?.content).toBe('历史')
    expect(state.isStreaming).toBe(false)
  })

  it('reset 清空全部会话相关状态', () => {
    useChatStore.getState().beginTurn('hi')
    useChatStore.getState().setConversationId('c-1')
    useChatStore.getState().setLoadingHistory(true)
    useChatStore.getState().reset()
    expect(useChatStore.getState()).toMatchObject({
      activeMessages: [],
      conversationId: '',
      isStreaming: false,
      loadingHistory: false,
    })
  })
})
