import { beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteConversation } from '@/lib/api'
import { useConversationsStore } from '@/stores/conversations'
import type { ConversationRecord } from '@/types'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, deleteConversation: vi.fn() }
})

function makeRecord(conversationId: string, updatedAt: string): ConversationRecord {
  return {
    conversation_id: conversationId,
    agent_id: null,
    model_provider: null,
    model_id: null,
    name: `会话 ${conversationId}`,
    summary: null,
    status: 'active',
    dialogue_count: 1,
    created_at: updatedAt,
    updated_at: updatedAt,
  }
}

const mockedDelete = vi.mocked(deleteConversation)

beforeEach(() => {
  mockedDelete.mockReset()
  useConversationsStore.setState({ items: [], loading: false })
})

describe('replaceAll', () => {
  it('按 updated_at 倒序排列', () => {
    useConversationsStore
      .getState()
      .replaceAll([
        makeRecord('old', '2026-01-01T00:00:00Z'),
        makeRecord('new', '2026-01-03T00:00:00Z'),
        makeRecord('mid', '2026-01-02T00:00:00Z'),
      ])
    expect(useConversationsStore.getState().items.map((i) => i.conversation_id)).toEqual([
      'new',
      'mid',
      'old',
    ])
  })
})

describe('add', () => {
  it('乐观入列并去重置顶', () => {
    useConversationsStore.getState().replaceAll([makeRecord('a', '2026-01-01T00:00:00Z')])
    useConversationsStore.getState().add(makeRecord('b', '2026-01-04T00:00:00Z'))
    useConversationsStore.getState().add(makeRecord('a', '2026-01-05T00:00:00Z'))
    const ids = useConversationsStore.getState().items.map((i) => i.conversation_id)
    expect(ids).toContain('a')
    expect(ids).toContain('b')
    expect(ids.filter((id) => id === 'a')).toHaveLength(1)
  })
})

describe('touch', () => {
  it('更新指定会话 updated_at 并置顶，其余对象引用不变', () => {
    useConversationsStore
      .getState()
      .replaceAll([
        makeRecord('a', '2026-01-01T00:00:00Z'),
        makeRecord('b', '2026-01-02T00:00:00Z'),
      ])
    const before = useConversationsStore.getState().items
    // touch 前按 updated_at 倒序：[b(01-02), a(01-01)]
    const untouchedB = before[0]
    useConversationsStore.getState().touch('a')
    const after = useConversationsStore.getState().items
    expect(after[0]?.conversation_id).toBe('a')
    // 未被 touch 的 b 保持引用不变（memo 稳定性）
    expect(after[1]).toBe(untouchedB)
  })
})

describe('remove', () => {
  it('204/成功 → 本地移除并返回 true', async () => {
    mockedDelete.mockResolvedValue(undefined)
    useConversationsStore.getState().replaceAll([makeRecord('a', '2026-01-01T00:00:00Z')])
    const ok = await useConversationsStore.getState().remove('a')
    expect(ok).toBe(true)
    expect(useConversationsStore.getState().items).toHaveLength(0)
  })

  it('404 视为已删除 → 本地移除并返回 true', async () => {
    mockedDelete.mockRejectedValue(new Error('404'))
    mockedDelete.mockRejectedValueOnce({
      response: { status: 404 },
    } as never)
    useConversationsStore.getState().replaceAll([makeRecord('a', '2026-01-01T00:00:00Z')])
    const ok = await useConversationsStore.getState().remove('a')
    expect(ok).toBe(true)
  })

  it('其他错误 → 保留条目并返回 false', async () => {
    mockedDelete.mockRejectedValue(new Error('500'))
    useConversationsStore.getState().replaceAll([makeRecord('a', '2026-01-01T00:00:00Z')])
    const ok = await useConversationsStore.getState().remove('a')
    expect(ok).toBe(false)
    expect(useConversationsStore.getState().items).toHaveLength(1)
  })
})
