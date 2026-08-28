import { describe, expect, it } from 'vitest'
import { mapMessageRecord, mapMessageRecords } from '@/lib/history'
import type { MessageRecord } from '@/types'

function makeRecord(overrides: Partial<MessageRecord> = {}): MessageRecord {
  return {
    message_id: 'm-1',
    conversation_id: 'c-1',
    agent_id: null,
    provider: null,
    model: null,
    query: '你好',
    answer: '你好！',
    thinking: null,
    status: 'normal',
    error: null,
    latency_ms: 100,
    prompt_tokens: 10,
    completion_tokens: 20,
    total_tokens: 30,
    cached_read_tokens: 0,
    cached_write_tokens: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:01Z',
    ...overrides,
  }
}

describe('mapMessageRecord', () => {
  it('正常记录 → 用户 + 助手两条消息', () => {
    const [user, assistant] = mapMessageRecord(makeRecord())
    expect(user).toMatchObject({
      id: 'm-1:user',
      role: 'user',
      content: '你好',
      status: 'done',
    })
    expect(assistant).toMatchObject({
      id: 'm-1',
      role: 'assistant',
      content: '你好！',
      status: 'done',
    })
  })

  it('错误记录 → 助手消息 error 态并带错误文案', () => {
    const [, assistant] = mapMessageRecord(makeRecord({ status: 'error', error: '服务内部错误' }))
    expect(assistant?.status).toBe('error')
    expect(assistant?.errorMessage).toBe('服务内部错误')
  })

  it('思考内容 → 助手消息 thinking 态（done，ThinkingPanel 折叠展示）', () => {
    const [, assistant] = mapMessageRecord(makeRecord({ thinking: '让我想想…' }))
    expect(assistant?.thinking).toBe('让我想想…')
    expect(assistant?.thinkingStatus).toBe('done')
  })

  it('answer 为 null → 助手消息空正文', () => {
    const [, assistant] = mapMessageRecord(makeRecord({ answer: null }))
    expect(assistant?.content).toBe('')
  })
})

describe('mapMessageRecords', () => {
  it('多条记录 flatMap 展开', () => {
    const messages = mapMessageRecords([
      makeRecord({ message_id: 'm-1' }),
      makeRecord({ message_id: 'm-2' }),
    ])
    expect(messages).toHaveLength(4)
    expect(messages.map((m) => m.id)).toEqual(['m-1:user', 'm-1', 'm-2:user', 'm-2'])
  })
})
