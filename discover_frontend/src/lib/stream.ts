/**
 * SSE 流读取 + 帧分发（CLAUDE.md 第 5 节）。
 * 纯消费层：ReadableStream → 判别联合帧 → 回调分发；不依赖 store / React，可单测。
 * 编排（驱动 store / AbortController / turn 作废）在 hooks/useChatStream.ts。
 */
import { type AppError, mapSseError, STREAM_INTERRUPTED } from '@/lib/errors'
import { createSseParser, parseFrameJson } from '@/lib/sse'
import type { SseStreamFrame, TurnMetadata } from '@/types'

/**
 * 流式对话读取：fetch Response 的 ReadableStream → 判别联合帧。
 * 帧解析原语在 lib/sse.ts（纯函数）；本文件只做读取、解码与类型化产出。
 * 取消由上游 AbortController 关联 fetch，取消后复位 store 流式状态（hooks 层）。
 */
export async function* readChatStream(response: Response): AsyncGenerator<SseStreamFrame> {
  if (!response.ok) {
    throw new Error(`对话请求失败：HTTP ${response.status}`)
  }
  if (response.body === null) {
    throw new Error('对话响应缺少流式 body')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  const parser = createSseParser()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      const frames = parser.push(decoder.decode(value, { stream: true }))
      for (const frame of frames) {
        const parsed = parseFrameJson<SseStreamFrame>(frame.data)
        if (parsed !== null) yield parsed
      }
    }
    const tail = parser.flush()
    for (const frame of tail) {
      const parsed = parseFrameJson<SseStreamFrame>(frame.data)
      if (parsed !== null) yield parsed
    }
  } finally {
    reader.releaseLock()
  }
}

/** 从响应头提取会话 ID（优先级：X-Conversation-Id 头；空串由帧内 conversation_id 兜底） */
export function readConversationId(response: Response): string {
  const header = response.headers.get('X-Conversation-Id')
  return header ?? ''
}

export interface ChatStreamHandlers {
  onDelta: (delta: string) => void
  onThinkingStart: () => void
  onThinkingDelta: (delta: string) => void
  onThinkingEnd: (durationMs: number) => void
  onEnd: (metadata: TurnMetadata, conversationId: string) => void
  onError: (error: AppError) => void
}

/**
 * v2 终态分流：message_end.metadata.status === "cancelled"（RunCancelled，用户 stop）
 * → 停止语义（空内容移除 / 非空保留并标记完成）；succeeded / partial / 缺省 → 正常完成。
 */
export function resolveTurnEnd(metadata: TurnMetadata): 'complete' | 'abort' {
  return metadata.status === 'cancelled' ? 'abort' : 'complete'
}

/**
 * 消费流：message → onDelta、thinking_* → 思考回调、message_end → onEnd、
 * error → onError、ping → 忽略。
 * 流自然结束（读到 EOF）但未到 message_end 视为异常中断，回调 STREAM_INTERRUPTED。
 * 读取期抛错（网络断开 / abort）向上传播，由编排层决定错误语义。
 */
export async function consumeChatStream(
  response: Response,
  handlers: ChatStreamHandlers,
): Promise<void> {
  // message_end / error 均为终止帧：到达即不再视为「异常中断」，避免重复报错
  let terminated = false
  for await (const frame of readChatStream(response)) {
    if (frame.event === 'message') {
      handlers.onDelta(frame.answer)
    } else if (frame.event === 'thinking_started') {
      handlers.onThinkingStart()
    } else if (frame.event === 'thinking_delta') {
      handlers.onThinkingDelta(frame.content)
    } else if (frame.event === 'thinking_ended') {
      handlers.onThinkingEnd(frame.duration_ms)
    } else if (frame.event === 'message_end') {
      terminated = true
      handlers.onEnd(frame.metadata, frame.conversation_id)
    } else if (frame.event === 'error') {
      terminated = true
      handlers.onError(mapSseError(frame))
    }
  }
  if (!terminated) {
    handlers.onError(STREAM_INTERRUPTED)
  }
}
