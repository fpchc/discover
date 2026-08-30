import { create } from 'zustand'
import { deleteConversation } from '@/lib/api'
import type { ConversationRecord } from '@/types'

// pragma: 简化 — 会话列表显示级缓存：避免刷新 / 重回对话页时侧栏闪加载骨架（三个空白）。
// 后端 GET /conversations 仍为唯一事实源，每次 loadList / reconcileList 全量覆盖校准；
// 本缓存仅为「网络就绪前的即时展示」，登出 / 过期经 resetAppState → replaceAll([]) 清空，防跨账号泄漏。
const CACHE_KEY = 'disf_conversations_cache'

function readCache(): ConversationRecord[] {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (raw === null) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as ConversationRecord[]) : []
  } catch {
    // 损坏 / 隐私模式不可读：走空列表
    return []
  }
}

function writeCache(items: ConversationRecord[]): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(items))
  } catch {
    // 隐私模式 / 容量超限：跳过缓存，仅内存态生效
  }
}

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

// 模块加载即读缓存：有缓存 → 立即展示、不置加载态；无缓存 → 置加载态，骨架占位直到首次拉取
const initialItems = readCache()

export const useConversationsStore = create<ConversationsState>((set) => ({
  items: initialItems,
  loading: initialItems.length === 0,

  setLoading: (value) => set({ loading: value }),

  /** 全量替换（loadList / reconcileList / 登出清空）：权威同步点，同时写显示级缓存 */
  replaceAll: (records) => {
    const items = sortByUpdatedAt(records)
    writeCache(items)
    return set({ items })
  },

  /** 新会话乐观入列（首轮 message_end 后由 loadList 校准后端权威值；乐观态不入缓存） */
  add: (record) =>
    set((state) => ({
      items: sortByUpdatedAt([
        record,
        ...state.items.filter((item) => item.conversation_id !== record.conversation_id),
      ]),
    })),

  /** 续聊：本地置顶；真实 updated_at / dialogue_count 由 loadList 校准（乐观态不入缓存） */
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

  /** 删除：调后端 DELETE；204/404 视为已删除并从本地移除（同步清缓存），其余错误返回 false 保留条目 */
  remove: async (conversationId) => {
    try {
      await deleteConversation(conversationId)
    } catch (err) {
      if (!isNotFound(err)) {
        return false
      }
    }
    set((state) => {
      const items = state.items.filter((item) => item.conversation_id !== conversationId)
      writeCache(items)
      return { items }
    })
    return true
  },
}))
