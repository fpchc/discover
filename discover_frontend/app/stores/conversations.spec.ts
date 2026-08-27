import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteConversation } from '@/api/history'
import type { ConversationRecord } from '@/api/types'
import { useConversationsStore } from './conversations'

vi.mock('@/api/history', () => ({
  deleteConversation: vi.fn(async () => undefined),
}))

function record(id: string, updatedAt: string): ConversationRecord {
  return {
    conversation_id: id,
    agent_id: null,
    model_provider: null,
    model_id: null,
    name: `会话-${id}`,
    summary: null,
    status: 'active',
    dialogue_count: 1,
    created_at: updatedAt,
    updated_at: updatedAt,
  }
}

describe('conversations store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('replaceAll 按 updated_at 倒序', () => {
    const store = useConversationsStore()
    store.replaceAll([
      record('a', '2026-01-01T00:00:00.000Z'),
      record('b', '2026-01-02T00:00:00.000Z'),
    ])
    expect(store.items.map((item) => item.conversation_id)).toEqual(['b', 'a'])
  })

  it('add 去重并按 updated_at 置顶', () => {
    const store = useConversationsStore()
    store.add(record('a', '2026-01-01T00:00:00.000Z'))
    store.add(record('b', '2026-01-02T00:00:00.000Z'))
    store.add(record('a', '2026-01-03T00:00:00.000Z'))
    expect(store.items).toHaveLength(2)
    expect(store.items[0].conversation_id).toBe('a')
    expect(store.items[1].conversation_id).toBe('b')
  })

  it('touch 本地刷新 updated_at 并置顶', () => {
    const store = useConversationsStore()
    store.replaceAll([
      record('a', '2026-01-01T00:00:00.000Z'),
      record('b', '2026-01-02T00:00:00.000Z'),
    ])
    store.touch('a')
    expect(store.items[0].conversation_id).toBe('a')
    expect(new Date(store.items[0].updated_at).getTime()).toBeGreaterThan(
      Date.parse('2026-01-02T00:00:00.000Z'),
    )
  })

  it('remove 调后端并移除指定会话', async () => {
    const store = useConversationsStore()
    store.replaceAll([
      record('a', '2026-01-01T00:00:00.000Z'),
      record('b', '2026-01-02T00:00:00.000Z'),
    ])
    vi.mocked(deleteConversation).mockResolvedValueOnce(undefined)
    expect(await store.remove('a')).toBe(true)
    expect(deleteConversation).toHaveBeenCalledWith('a')
    expect(store.items.map((item) => item.conversation_id)).toEqual(['b'])
  })

  it('remove 删除失败保留条目', async () => {
    const store = useConversationsStore()
    store.replaceAll([record('a', '2026-01-01T00:00:00.000Z')])
    vi.mocked(deleteConversation).mockRejectedValueOnce(new Error('network'))
    expect(await store.remove('a')).toBe(false)
    expect(store.items.map((item) => item.conversation_id)).toEqual(['a'])
  })

  it('remove 遇 404 视为已删除', async () => {
    const store = useConversationsStore()
    store.replaceAll([record('a', '2026-01-01T00:00:00.000Z')])
    vi.mocked(deleteConversation).mockRejectedValueOnce({ response: { status: 404 } })
    expect(await store.remove('a')).toBe(true)
    expect(store.items).toHaveLength(0)
  })

  it('setLoading 控制列表加载态', () => {
    const store = useConversationsStore()
    expect(store.loading).toBe(false)
    store.setLoading(true)
    expect(store.loading).toBe(true)
  })
})
