import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ConversationRecord } from '@/api/types'

function sortByUpdatedAt(items: ConversationRecord[]): ConversationRecord[] {
  return [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

/**
 * 会话列表状态（后端 GET /conversations 为唯一事实源，见 API.md §1）。
 * 本层只做纯状态变更，不发起 HTTP；拉取 / 校准由 useChatStream.loadList 编排。
 * 删除为前端本地移除（后端无删除接口）。
 */
export const useConversationsStore = defineStore('conversations', () => {
  const items = ref<ConversationRecord[]>([])
  const loading = ref<boolean>(false)

  /** 以后端权威列表整体替换（含加载中标志，由编排层驱动） */
  function setLoading(value: boolean): void {
    loading.value = value
  }

  function replaceAll(records: ConversationRecord[]): void {
    items.value = sortByUpdatedAt(records)
  }

  /** 新会话乐观入列（首轮 message_end 后由 loadList 校准后端权威值） */
  function add(record: ConversationRecord): void {
    items.value = sortByUpdatedAt([
      record,
      ...items.value.filter((item) => item.conversation_id !== record.conversation_id),
    ])
  }

  /** 续聊：本地置顶；真实 updated_at / dialogue_count 由 loadList 校准 */
  function touch(conversationId: string): void {
    const now = new Date().toISOString()
    items.value = sortByUpdatedAt(
      items.value.map((item) =>
        item.conversation_id === conversationId ? { ...item, updated_at: now } : item,
      ),
    )
  }

  /** 删除（仅前端本地移除；后端无删除接口，刷新后会话仍由后端带回） */
  function remove(conversationId: string): void {
    items.value = items.value.filter((item) => item.conversation_id !== conversationId)
  }

  return { items, loading, setLoading, replaceAll, add, touch, remove }
})
