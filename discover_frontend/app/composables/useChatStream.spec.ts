import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchAssistants } from '@/api/assistants'
import { sendChatMessage, sendChatMessageBlocking } from '@/api/chat'
import { fetchConversations, fetchConversationUsage, fetchMessages } from '@/api/history'
import type { AssistantInfo, UsageInfo } from '@/api/types'
import { GENERIC_ASSISTANT_ID, useAssistantsStore } from '@/stores/assistants'
import { useChatStore } from '@/stores/chat'
import { consumeChatStream, useChatStream } from './useChatStream'

vi.mock('@/api/chat', () => ({
  sendChatMessage: vi.fn(),
  sendChatMessageBlocking: vi.fn(),
}))

vi.mock('@/api/history', () => ({
  fetchConversations: vi.fn(),
  fetchConversationUsage: vi.fn(),
  fetchMessages: vi.fn(),
}))

vi.mock('@/api/assistants', () => ({
  fetchAssistants: vi.fn(),
}))

function frame(event: object): string {
  return `data: ${JSON.stringify(event)}`
}

/** 构造一次性吐出完整 SSE 文本的 Response（happy-dom / Node 均支持 ReadableStream） */
function streamResponse(sseText: string): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(sseText))
      controller.close()
    },
  })
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

describe('consumeChatStream', () => {
  it('按判别帧分发 onDelta / onEnd，ping 忽略，无错误', async () => {
    const deltas: string[] = []
    let endPayload: { usage?: UsageInfo; conversationId: string } | undefined
    const errors: string[] = []
    const sse = `${[
      frame({ event: 'ping' }),
      frame({
        event: 'message',
        message_id: 'm1',
        conversation_id: 'c1',
        answer: '你',
        created_at: 1,
      }),
      frame({
        event: 'message',
        message_id: 'm1',
        conversation_id: 'c1',
        answer: '好',
        created_at: 1,
      }),
      frame({
        event: 'message_end',
        message_id: 'm1',
        conversation_id: 'c1',
        metadata: { usage: { total_tokens: 3 } },
        created_at: 1,
      }),
    ].join('\n\n')}\n\n`

    await consumeChatStream(streamResponse(sse), {
      onDelta: (delta) => deltas.push(delta),
      onThinkingStart: () => {},
      onThinkingDelta: () => {},
      onThinkingEnd: () => {},
      onEnd: (metadata, conversationId) => {
        endPayload = { usage: metadata.usage, conversationId }
      },
      onError: (error) => errors.push(error.message),
    })

    expect(deltas).toEqual(['你', '好'])
    expect(endPayload).toEqual({ usage: { total_tokens: 3 }, conversationId: 'c1' })
    expect(errors).toEqual([])
  })

  it('流自然结束未到 message_end → 报 STREAM_INTERRUPTED 并保留已收内容', async () => {
    const deltas: string[] = []
    const errors: string[] = []
    const sse = `${frame({
      event: 'message',
      message_id: 'm1',
      conversation_id: 'c1',
      answer: '半截',
      created_at: 1,
    })}\n\n`

    await consumeChatStream(streamResponse(sse), {
      onDelta: (delta) => deltas.push(delta),
      onThinkingStart: () => {},
      onThinkingDelta: () => {},
      onThinkingEnd: () => {},
      onEnd: () => {},
      onError: (error) => errors.push(error.message),
    })

    expect(deltas).toEqual(['半截'])
    expect(errors).toEqual(['连接中断，已保留已接收内容'])
  })

  it('error 帧映射为可读文案', async () => {
    const errors: string[] = []
    const sse = `${frame({ event: 'error', status: 429, code: 'rate_limit', message: '限流' })}\n\n`

    await consumeChatStream(streamResponse(sse), {
      onDelta: () => {},
      onThinkingStart: () => {},
      onThinkingDelta: () => {},
      onThinkingEnd: () => {},
      onEnd: () => {},
      onError: (error) => errors.push(error.message),
    })

    expect(errors).toEqual(['限流'])
  })

  it('HTTP 非 2xx 抛错（由编排层映射）', async () => {
    const response = new Response('server error', { status: 500 })
    await expect(
      consumeChatStream(response, {
        onDelta: () => {},
        onThinkingStart: () => {},
        onThinkingDelta: () => {},
        onThinkingEnd: () => {},
        onEnd: () => {},
        onError: () => {},
      }),
    ).rejects.toThrow()
  })

  it('按序分发 thinking_started / thinking_delta / thinking_ended', async () => {
    const thinkingStarts: number[] = []
    const thinkingDeltas: string[] = []
    const thinkingEnds: number[] = []
    const sse = `${[
      frame({ event: 'thinking_started', message_id: 'm1', conversation_id: 'c1', created_at: 1 }),
      frame({
        event: 'thinking_delta',
        message_id: 'm1',
        conversation_id: 'c1',
        content: '先分析产业链',
        created_at: 1,
      }),
      frame({
        event: 'thinking_delta',
        message_id: 'm1',
        conversation_id: 'c1',
        content: '再圈定候选客户',
        created_at: 1,
      }),
      frame({
        event: 'thinking_ended',
        message_id: 'm1',
        conversation_id: 'c1',
        duration_ms: 8123,
        created_at: 1,
      }),
      frame({
        event: 'message',
        message_id: 'm1',
        conversation_id: 'c1',
        answer: '# 报告',
        created_at: 1,
      }),
      frame({
        event: 'message_end',
        message_id: 'm1',
        conversation_id: 'c1',
        metadata: {},
        created_at: 1,
      }),
    ].join('\n\n')}\n\n`

    await consumeChatStream(streamResponse(sse), {
      onDelta: () => {},
      onThinkingStart: () => thinkingStarts.push(1),
      onThinkingDelta: (delta) => thinkingDeltas.push(delta),
      onThinkingEnd: (durationMs) => thinkingEnds.push(durationMs),
      onEnd: () => {},
      onError: () => {},
    })

    expect(thinkingStarts).toHaveLength(1)
    expect(thinkingDeltas).toEqual(['先分析产业链', '再圈定候选客户'])
    expect(thinkingEnds).toEqual([8123])
  })

  it('仅收到 thinking_* 帧未到 message_end → 仍视为流中断', async () => {
    const errors: string[] = []
    const sse = `${[
      frame({ event: 'thinking_started', message_id: 'm1', conversation_id: 'c1', created_at: 1 }),
      frame({
        event: 'thinking_delta',
        message_id: 'm1',
        conversation_id: 'c1',
        content: '思考中',
        created_at: 1,
      }),
    ].join('\n\n')}\n\n`

    await consumeChatStream(streamResponse(sse), {
      onDelta: () => {},
      onThinkingStart: () => {},
      onThinkingDelta: () => {},
      onThinkingEnd: () => {},
      onEnd: () => {},
      onError: (error) => errors.push(error.message),
    })

    expect(errors).toEqual(['连接中断，已保留已接收内容'])
  })
})

// ===================== 编排层：连续对话（conversation_id 贯穿） =====================

/** message_end 收尾帧 SSE 体（含 conversation_id） */
function messageEndSse(conversationId: string): string {
  return `data: ${JSON.stringify({
    event: 'message_end',
    message_id: 'm1',
    conversation_id: conversationId,
    metadata: { usage: { total_tokens: 3 } },
    created_at: 1,
  })}\n\n`
}

/** 构造流式 Response：withHeader=false 时无 X-Conversation-Id（仅帧内回填路径） */
function sseResponse(conversationId: string, withHeader = true): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(messageEndSse(conversationId)))
      controller.close()
    },
  })
  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      ...(withHeader ? { 'X-Conversation-Id': conversationId } : {}),
    },
  })
}

/** 含 metadata.assistant 的 message_end 帧流式 Response（回显路径） */
function assistantEchoSse(assistant: AssistantInfo): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(
          `data: ${JSON.stringify({
            event: 'message_end',
            message_id: 'm1',
            conversation_id: 'cid-a',
            metadata: { usage: { total_tokens: 3 }, assistant },
            created_at: 1,
          })}\n\n`,
        ),
      )
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

describe('useChatStream 连续对话（conversation_id 贯穿）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(sendChatMessage).mockReset()
    vi.mocked(sendChatMessageBlocking).mockReset()
    vi.mocked(fetchConversations).mockReset()
    vi.mocked(fetchConversationUsage).mockReset()
    vi.mocked(fetchMessages).mockReset()
    vi.mocked(fetchAssistants).mockReset()
    vi.mocked(fetchConversations).mockResolvedValue([])
    vi.mocked(fetchMessages).mockResolvedValue([])
  })

  it('第二轮请求复用第一轮响应返回的 conversation_id（头 + 帧双路径）', async () => {
    const chat = useChatStore()
    const stream = useChatStream()

    // 后端按请求中的会话 ID 回显：空串分配 cid-1，续聊沿用
    vi.mocked(sendChatMessage).mockImplementation(async (params) =>
      sseResponse(params.conversationId === '' ? 'cid-1' : params.conversationId),
    )

    await stream.send('你好')
    expect(chat.conversationId).toBe('cid-1')
    expect(sendChatMessage).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ conversationId: '' }),
    )

    await stream.send('继续说')
    expect(chat.conversationId).toBe('cid-1')
    expect(sendChatMessage).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ conversationId: 'cid-1' }),
    )
  })

  it('无响应头时，帧内 conversation_id 兜底回填并支持续聊', async () => {
    const chat = useChatStore()
    const stream = useChatStream()

    vi.mocked(sendChatMessage).mockImplementation(async (params) =>
      sseResponse(params.conversationId === '' ? 'cid-2' : params.conversationId, false),
    )

    await stream.send('你好')
    expect(chat.conversationId).toBe('cid-2')

    await stream.send('继续说')
    expect(sendChatMessage).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ conversationId: 'cid-2' }),
    )
  })

  it('每次发送带上当前选择的 agent_id', async () => {
    const assistants = useAssistantsStore()
    const stream = useChatStream()

    assistants.select('discover')
    vi.mocked(sendChatMessage).mockResolvedValue(
      assistantEchoSse({ type: 'expert', id: 'discover' }),
    )

    await stream.send('帮我找客户')

    expect(sendChatMessage).toHaveBeenCalledWith(expect.objectContaining({ agentId: 'discover' }))
  })

  it('回合结束按 metadata.assistant 回显选择器（专家 / 通用）', async () => {
    const assistants = useAssistantsStore()
    const stream = useChatStream()

    assistants.select('discover')
    vi.mocked(sendChatMessage).mockResolvedValue(
      assistantEchoSse({ type: 'expert', id: 'discover' }),
    )
    await stream.send('帮我找客户')
    expect(assistants.selectedId).toBe('discover')

    assistants.select(GENERIC_ASSISTANT_ID)
    vi.mocked(sendChatMessage).mockResolvedValue(assistantEchoSse({ type: 'generic', id: null }))
    await stream.send('你好')
    expect(assistants.selectedId).toBe(GENERIC_ASSISTANT_ID)
  })

  it('loadAssistants 拉取目录并落到默认通用', async () => {
    const assistants = useAssistantsStore()
    const stream = useChatStream()

    vi.mocked(fetchAssistants).mockResolvedValue([
      {
        id: 'discover',
        type: 'expert',
        name: '客户发现',
        description: '寻找潜在客户',
        capabilities: [],
      },
      {
        id: 'generic',
        type: 'generic',
        name: '通用对话',
        description: '日常问答',
        capabilities: [],
      },
    ])

    await stream.loadAssistants()

    expect(assistants.catalog).toHaveLength(2)
    expect(assistants.selectedId).toBe(GENERIC_ASSISTANT_ID)
    expect(assistants.loading).toBe(false)
  })
})
