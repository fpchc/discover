import { create } from 'zustand'
import { deleteConversation } from '@/lib/api'
import type { ConversationRecord } from '@/types'

/**
 * 会话列表状态（后端 GET /conversations 为唯一事实源，见 API.md §1）。
 * 本层只做纯状态变更，不发起 HTTP；拉取 / 校准由 hooks/useChatStream 编排。
 * 删除调后端 DELETE /conversations/{id}（204/404 均视为已删除，其余错误保留条目）。
 * 注意：本 store 与 chat 的 activeMessages 解耦，流式增量不触碰此处（粒度红线，见 performance.md）。
 */
export interface ConversationsState {
  items: ConversationRecord[]
  loading: boolean
  setLoading: (value: boolean) => void
  replaceAll: (records: ConversationRecord[]) => void
  add: (record: ConversationRecord) => void
  touch: (conversationId: string) => void
  remove: (conversationId: string) => Promise<boolean>
}

function sortByUpdatedAt(items: ConversationRecord[]): ConversationRecord[] {
  return [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

/** 后端 404 判断：会话已被删除（axios 错误体 `.response.status`）。 */
function isNotFound(err: unknown): boolean {
  const status = (err as { response?: { status?: unknown } } | null)?.response?.status
  return status === 404
}

export const useConversationsStore = create<ConversationsState>((set) => ({
  items: [],
  loading: false,

  setLoading: (value) => set({ loading: value }),

  replaceAll: (records) => set({ items: sortByUpdatedAt(records) }),

  /** 新会话乐观入列（首轮 message_end 后由 loadList 校准后端权威值） */
  add: (record) =>
    set((state) => ({
      items: sortByUpdatedAt([
        record,
        ...state.items.filter((item) => item.conversation_id !== record.conversation_id),
      ]),
    })),

  /** 续聊：本地置顶；真实 updated_at / dialogue_count 由 loadList 校准 */
  touch: (conversationId) =>
    set((state) => {
      const now = new Date().toISOString()
      return {
        items: sortByUpdatedAt(
          state.items.map((item) =>
            item.conversation_id === conversationId ? { ...item, updated_at: now } : item,
          ),
        ),
      }
    }),

  /** 删除：调后端 DELETE；204/404 视为已删除并从本地移除，其余错误返回 false 保留条目 */
  remove: async (conversationId) => {
    try {
      await deleteConversation(conversationId)
    } catch (err) {
      if (!isNotFound(err)) {
        return false
      }
    }
    set((state) => ({
      items: state.items.filter((item) => item.conversation_id !== conversationId),
    }))
    return true
  },
}))
