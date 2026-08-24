import { sendChatMessage, sendChatMessageBlocking } from '@/api/chat'
import {
  type AppError,
  HttpError,
  mapHttpError,
  mapSseError,
  readResponseError,
  STREAM_INTERRUPTED,
  TIMEOUT_ERROR,
} from '@/api/errors'
import type { SseStreamFrame, UsageInfo } from '@/api/types'
import {
  CHAT_QUERY_MAX,
  CONVERSATION_TITLE_MAX,
  FEATURE_BLOCKING_FALLBACK,
  SSE_TIMEOUT_MS,
} from '@/config/env'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import { createSseParser, parseFrameJson } from '@/utils/sse'

// ===================== 纯读取层：ReadableStream → 判别联合帧 =====================

/**
 * 流式对话读取：fetch Response 的 ReadableStream → 判别联合帧。
 * 帧解析原语在 utils/sse.ts（纯函数）；本文件只做读取、解码与类型化产出。
 * 取消由上游 AbortController 关联 fetch，取消后复位 store 流式状态。
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

// ===================== 纯消费层：帧分发到回调（不依赖 store，可单测） =====================

export interface ChatStreamHandlers {
  onDelta: (delta: string) => void
  onEnd: (metadata: { usage?: UsageInfo }, conversationId: string) => void
  onError: (error: AppError) => void
}

/**
 * 消费流：message → onDelta、message_end → onEnd、error → onError、ping → 忽略。
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

// ===================== 编排层：驱动 store（HTTP / SSE 唯一消费方） =====================

/**
 * 对话发送编排。职责：
 * - 会话首次创建 / 续聊复用（X-Conversation-Id 头优先，帧内 id 兜底）；
 * - 流式 / 阻塞（兜底）两种 response_mode；
 * - AbortController 取消 + SSE_TIMEOUT_MS 整体超时；
 * - turn token 作废机制：切换 / 新建会话后，旧流的残留帧与回调不再落库（防幽灵增量）。
 */
export function useChatStream() {
  const chat = useChatStore()
  const conversations = useConversationsStore()

  let controller: AbortController | null = null
  let userCancelled = false
  let lastQuery = ''
  let turnSeq = 0

  function isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === 'AbortError'
  }

  function registerConversation(conversationId: string): void {
    const isNew = chat.conversationId === ''
    chat.setConversationId(conversationId)
    if (isNew) {
      conversations.add({
        conversation_id: conversationId,
        title: lastQuery.slice(0, CONVERSATION_TITLE_MAX),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      })
    } else {
      conversations.touch(conversationId)
    }
  }

  async function runTurn(query: string, mode: 'streaming' | 'blocking'): Promise<void> {
    const turn = ++turnSeq
    userCancelled = false
    const localController = new AbortController()
    controller = localController
    const timeoutId = window.setTimeout(() => localController.abort(), SSE_TIMEOUT_MS)
    const isCurrent = (): boolean => turn === turnSeq

    try {
      if (mode === 'blocking') {
        const data = await sendChatMessageBlocking({
          query,
          conversationId: chat.conversationId,
          signal: localController.signal,
        })
        if (!isCurrent()) return
        registerConversation(data.conversation_id)
        chat.completeAssistant(data.metadata.usage)
        return
      }

      const response = await sendChatMessage({
        query,
        conversationId: chat.conversationId,
        signal: localController.signal,
      })
      if (!response.ok) {
        throw await readResponseError(response)
      }
      const headerId = readConversationId(response)
      if (headerId !== '') {
        if (!isCurrent()) return
        registerConversation(headerId)
      }
      await consumeChatStream(response, {
        onDelta: (delta) => {
          if (isCurrent()) chat.appendDelta(delta)
        },
        onEnd: (metadata, conversationId) => {
          if (!isCurrent()) return
          if (conversationId !== '') registerConversation(conversationId)
          chat.completeAssistant(metadata.usage)
        },
        onError: (error) => {
          if (isCurrent()) chat.failAssistant(error.message)
        },
      })
    } catch (error) {
      if (!isCurrent()) return
      if (userCancelled) {
        chat.abortTurn()
      } else if (isAbortError(error)) {
        chat.failAssistant(TIMEOUT_ERROR.message)
      } else if (error instanceof HttpError) {
        chat.failAssistant(error.appError.message)
      } else {
        chat.failAssistant(mapHttpError(error).message)
      }
    } finally {
      if (isCurrent()) window.clearTimeout(timeoutId)
    }
  }

  async function send(query: string): Promise<void> {
    if (chat.isStreaming) return
    const trimmed = query.trim()
    if (trimmed === '' || trimmed.length > CHAT_QUERY_MAX) return
    lastQuery = trimmed
    chat.beginTurn(trimmed)
    await runTurn(trimmed, 'streaming')
  }

  /** 失败重试：优先走 blocking 兜底（受功能开关控制），不再追加用户消息 */
  async function retry(): Promise<void> {
    if (chat.isStreaming || lastQuery === '') return
    chat.beginRetryTurn()
    await runTurn(lastQuery, FEATURE_BLOCKING_FALLBACK ? 'blocking' : 'streaming')
  }

  /** 停止生成：保留已收内容，复位流式状态（F5） */
  function stop(): void {
    if (!chat.isStreaming) return
    userCancelled = true
    controller?.abort()
  }

  /** 切换 / 新建会话：作废当前轮 token，旧流残留帧不再落库 */
  function cancel(): void {
    userCancelled = true
    turnSeq += 1
    controller?.abort()
    controller = null
  }

  return { send, retry, stop, cancel }
}
