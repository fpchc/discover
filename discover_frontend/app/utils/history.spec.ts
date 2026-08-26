import { describe, expect, it } from 'vitest'
import type { MessageRecord } from '@/api/types'
import { mapMessageRecord, mapMessageRecords } from './history'

function record(overrides: Partial<MessageRecord> = {}): MessageRecord {
  return {
    message_id: 'm1',
    conversation_id: 'c1',
    agent_id: null,
    provider: null,
    model: null,
    query: '用户问题',
    answer: '助手回答',
    thinking: null,
    status: 'normal',
    error: null,
    latency_ms: 1234,
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    cached_read_tokens: 80,
    cached_write_tokens: 20,
    created_at: '2026-08-26T11:05:00',
    updated_at: '2026-08-26T11:05:00',
    ...overrides,
  }
}

describe('mapMessageRecord', () => {
  it('一回合映射为用户气泡 + 助手气泡两条', () => {
    const messages = mapMessageRecord(record())
    expect(messages).toHaveLength(2)
    expect(messages[0]).toMatchObject({ role: 'user', content: '用户问题', status: 'done' })
    expect(messages[1]).toMatchObject({ role: 'assistant', content: '助手回答', status: 'done' })
    // 用户气泡 key 不与助手真实 message_id 冲突
    expect(messages[0].id).toBe('m1:user')
    expect(messages[1].id).toBe('m1')
  })

  it('error 回合 → 助手 error 态并带 errorMessage', () => {
    const messages = mapMessageRecord(record({ status: 'error', error: '模型超时' }))
    expect(messages[1].status).toBe('error')
    expect(messages[1].errorMessage).toBe('模型超时')
  })

  it('error 字段为空串时不带 errorMessage', () => {
    const messages = mapMessageRecord(record({ status: 'error', error: '' }))
    expect(messages[1].status).toBe('error')
    expect(messages[1].errorMessage).toBeUndefined()
  })

  it('thinking → 思考分区（done 折叠态，不含耗时）', () => {
    const messages = mapMessageRecord(record({ thinking: '先圈定成都地区' }))
    expect(messages[1].thinking).toBe('先圈定成都地区')
    expect(messages[1].thinkingStatus).toBe('done')
  })

  it('usage 五键原样带出', () => {
    const messages = mapMessageRecord(record())
    expect(messages[1].usage).toEqual({
      prompt_tokens: 100,
      completion_tokens: 50,
      total_tokens: 150,
      cached_read_tokens: 80,
      cached_write_tokens: 20,
    })
  })

  it('answer 为 null → 助手空正文', () => {
    const messages = mapMessageRecord(record({ answer: null }))
    expect(messages[1].content).toBe('')
  })

  it('mapMessageRecords 按序平铺', () => {
    const records = [record({ message_id: 'm1' }), record({ message_id: 'm2', query: 'q2' })]
    const messages = mapMessageRecords(records)
    expect(messages).toHaveLength(4)
    expect(messages[0].id).toBe('m1:user')
    expect(messages[2].id).toBe('m2:user')
    expect(messages[3].id).toBe('m2')
  })
})
