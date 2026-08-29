import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useViewStore } from '@/stores/view'

/**
 * 视图持久化（CLAUDE.md §11：UI 状态走 localStorage，disf_ 前缀）。
 * 验证「刷新停留当前页面」：setView/setCenterTab 写入 localStorage，store 重建时读回。
 */
describe('useViewStore 视图持久化', () => {
  beforeEach(() => {
    localStorage.clear()
    useViewStore.setState({ view: 'chat', centerTab: 'profile', savedConversationId: '' })
  })

  it('默认：对话页 + 个人中心菜单 + 无会话', () => {
    expect(useViewStore.getState().view).toBe('chat')
    expect(useViewStore.getState().centerTab).toBe('profile')
    expect(useViewStore.getState().savedConversationId).toBe('')
  })

  it('切换后写入 localStorage（disf_ 前缀）', () => {
    useViewStore.getState().setView('center')
    useViewStore.getState().setCenterTab('usage')
    useViewStore.getState().setSavedConversationId('conv-123')
    expect(localStorage.getItem('disf_view')).toBe('center')
    expect(localStorage.getItem('disf_center_tab')).toBe('usage')
    expect(localStorage.getItem('disf_conversation_id')).toBe('conv-123')
  })

  it('重建 store 时从 localStorage 恢复（模拟刷新）', async () => {
    localStorage.setItem('disf_view', 'center')
    localStorage.setItem('disf_center_tab', 'usage')
    localStorage.setItem('disf_conversation_id', 'conv-123')
    vi.resetModules()
    const fresh = await import('@/stores/view')
    expect(fresh.useViewStore.getState().view).toBe('center')
    expect(fresh.useViewStore.getState().centerTab).toBe('usage')
    expect(fresh.useViewStore.getState().savedConversationId).toBe('conv-123')
  })

  it('非法值回退默认（chat / profile / 空会话）', async () => {
    localStorage.setItem('disf_view', 'not-a-view')
    localStorage.setItem('disf_center_tab', 'nope')
    localStorage.setItem('disf_conversation_id', '') // 空值合法，等同无会话
    vi.resetModules()
    const fresh = await import('@/stores/view')
    expect(fresh.useViewStore.getState().view).toBe('chat')
    expect(fresh.useViewStore.getState().centerTab).toBe('profile')
    expect(fresh.useViewStore.getState().savedConversationId).toBe('')
  })
})
