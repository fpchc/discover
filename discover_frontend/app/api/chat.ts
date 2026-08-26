import { API_BASE_URL } from '@/config/env'
import { httpClient } from './client'
import type { BlockingChatResponse, ChatRequest } from './types'

export interface SendChatMessageParams {
  query: string
  /** 空串 = 新建会话；续聊必带后端回传的会话 ID */
  conversationId: string
  /** 当前选中的助手 id（API.md §6.2）；空串 = 不显式选择（首轮走通用 / 续聊沿用已绑定） */
  agentId: string
  signal: AbortSignal
}

/** 组装对话请求体；agent_id 为空时省略（避免向后端传空串） */
function buildChatRequest(
  params: SendChatMessageParams,
  responseMode: 'streaming' | 'blocking',
): ChatRequest {
  return {
    query: params.query,
    response_mode: responseMode,
    conversation_id: params.conversationId,
    ...(params.agentId !== '' ? { agent_id: params.agentId } : {}),
  }
}

/**
 * 发起流式对话请求。
 * SSE 必须用 fetch + ReadableStream（POST 语义，不能用 EventSource）；
 * 返回未消费的 Response，交由 useChatStream 读取帧。
 */
export function sendChatMessage(params: SendChatMessageParams): Promise<Response> {
  return fetch(`${API_BASE_URL}/chat-messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(buildChatRequest(params, 'streaming')),
    signal: params.signal,
  })
}

/**
 * 阻塞模式对话（axios 普通 HTTP 出口）。
 * 用于流式失败的兜底重试（F6，受 VITE_FEATURE_BLOCKING_FALLBACK 开关控制）；
 * 返回后端 chat-messages JSON。
 */
export async function sendChatMessageBlocking(
  params: SendChatMessageParams,
): Promise<BlockingChatResponse> {
  const { data } = await httpClient.post<BlockingChatResponse>(
    '/chat-messages',
    buildChatRequest(params, 'blocking'),
    { signal: params.signal },
  )
  return data
}
