import { describe, expect, it } from 'vitest'
import type { UsageInfo } from '@/api/types'
import { consumeChatStream } from './useChatStream'

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
        onEnd: () => {},
        onError: () => {},
      }),
    ).rejects.toThrow()
  })
})
