/**
 * 历史消息映射（纯函数）：后端 MessageRecord（一回合 query+answer 同行）
 * → 前端 ChatMessage[]（用户气泡 + 助手气泡两条）。
 * 供 hooks/useChatStream.openConversation 消费；不依赖 React / DOM，可单测。
 */
import type { ChatMessage, MessageRecord } from '@/types'

export function mapMessageRecord(record: MessageRecord): ChatMessage[] {
  const userMessage: ChatMessage = {
    // 用户气泡无后端独立 ID，追加 `:user` 后缀与助手真实 message_id 区分 key
    id: `${record.message_id}:user`,
    role: 'user',
    content: record.query,
    created_at: record.created_at,
    status: 'done',
  }

  const assistantMessage: ChatMessage = {
    id: record.message_id,
    role: 'assistant',
    content: record.answer ?? '',
    created_at: record.created_at,
    status: record.status === 'error' ? 'error' : 'done',
  }
  if (record.status === 'error' && record.error !== null && record.error !== '') {
    assistantMessage.errorMessage = record.error
  }
  if (record.thinking !== null && record.thinking !== '') {
    assistantMessage.thinking = record.thinking
    // 历史记录的思考为已完成态（后端不存耗时），折叠展示
    assistantMessage.thinkingStatus = 'done'
  }

  return [userMessage, assistantMessage]
}

export function mapMessageRecords(records: MessageRecord[]): ChatMessage[] {
  return records.flatMap(mapMessageRecord)
}
