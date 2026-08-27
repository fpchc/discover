/**
 * 会话接口封装（API.md §1）。
 * 会话列表 / 消息流 / 用量汇总 / 删除均由后端持有，前端唯一消费方。
 * 分页：limit 1–200（默认 100），offset 默认 0；v1 不翻页。
 */
import { httpClient } from './client'
import type { ConversationRecord, ConversationUsage, MessageRecord } from './types'

const DEFAULT_LIMIT = 100

export async function fetchConversations(
  limit = DEFAULT_LIMIT,
  offset = 0,
): Promise<ConversationRecord[]> {
  const { data } = await httpClient.get<ConversationRecord[]>('/conversations', {
    params: { limit, offset },
  })
  return data
}

export async function fetchMessages(
  conversationId: string,
  limit = DEFAULT_LIMIT,
  offset = 0,
): Promise<MessageRecord[]> {
  const { data } = await httpClient.get<MessageRecord[]>(
    `/conversations/${conversationId}/messages`,
    { params: { limit, offset } },
  )
  return data
}

export async function fetchConversationUsage(conversationId: string): Promise<ConversationUsage> {
  const { data } = await httpClient.get<ConversationUsage>(`/conversations/${conversationId}/usage`)
  return data
}

/** 删除会话（204 成功；404 视为已删除，由调用方按「已删除」处理） */
export async function deleteConversation(conversationId: string): Promise<void> {
  await httpClient.delete(`/conversations/${conversationId}`)
}
