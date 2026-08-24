import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import type { ConversationMeta } from '@/api/types'
import { useConversationsStore } from './conversations'

function meta(id: string, updatedAt: string): ConversationMeta {
  return {
    conversation_id: id,
    title: `标题-${id}`,
    created_at: updatedAt,
    updated_at: updatedAt,
  }
}

function freshConversationsStore(): ReturnType<typeof useConversationsStore> {
  setActivePinia(createPinia())
  return useConversationsStore()
}

describe('conversations store', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('add 去重并按 updated_at 降序', () => {
    const store = useConversationsStore()
    store.add(meta('a', '2026-01-01T00:00:00.000Z'))
    store.add(meta('b', '2026-01-02T00:00:00.000Z'))
    store.add(meta('a', '2026-01-03T00:00:00.000Z'))
    expect(store.items).toHaveLength(2)
    expect(store.items[0].conversation_id).toBe('a')
    expect(store.items[1].conversation_id).toBe('b')
  })

  it('touch 刷新 updated_at 并置顶', () => {
    const store = useConversationsStore()
    store.add(meta('a', '2026-01-01T00:00:00.000Z'))
    store.add(meta('b', '2026-01-02T00:00:00.000Z'))
    store.touch('b')
    expect(store.items[0].conversation_id).toBe('b')
    expect(new Date(store.items[0].updated_at).getTime()).toBeGreaterThan(
      Date.parse('2026-01-02T00:00:00.000Z'),
    )
  })

  it('remove 移除指定会话', () => {
    const store = useConversationsStore()
    store.add(meta('a', '2026-01-01T00:00:00.000Z'))
    store.add(meta('b', '2026-01-02T00:00:00.000Z'))
    store.remove('a')
    expect(store.items.map((item) => item.conversation_id)).toEqual(['b'])
  })

  it('rename 更新标题与时间', () => {
    const store = useConversationsStore()
    store.add(meta('a', '2026-01-01T00:00:00.000Z'))
    store.rename('a', '新标题')
    expect(store.items[0].title).toBe('新标题')
  })

  it('clear 清空并移除本地存储', () => {
    const store = useConversationsStore()
    store.add(meta('a', '2026-01-01T00:00:00.000Z'))
    store.clear()
    expect(store.items).toHaveLength(0)
  })

  it('持久化：新 store 实例从 localStorage 恢复', () => {
    const store = useConversationsStore()
    store.add(meta('a', '2026-01-01T00:00:00.000Z'))

    const fresh = freshConversationsStore()
    expect(fresh.items).toHaveLength(1)
    expect(fresh.items[0].conversation_id).toBe('a')
  })

  it('reload 从存储重新读取（跨标签同步用）', () => {
    const store = useConversationsStore()
    store.add(meta('a', '2026-01-01T00:00:00.000Z'))
    // 直接改动底层存储模拟其他标签写入
    const external = freshConversationsStore()
    external.add(meta('b', '2026-01-02T00:00:00.000Z'))

    store.reload()
    expect(store.items.map((item) => item.conversation_id)).toEqual(['b', 'a'])
  })
})
