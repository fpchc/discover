import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ConversationMeta } from '@/api/types'
import { getPrefixedKey, loadFromStorage, removeFromStorage, saveToStorage } from '@/utils/persist'

const STORAGE_KEY = 'conversations'
const STORAGE_EVENT_KEY = getPrefixedKey(STORAGE_KEY)

function sortByUpdatedAt(items: ConversationMeta[]): ConversationMeta[] {
  return [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
}

// 跨标签页 storage 事件仅需注册一次（store 为单例）；标志防测试多 pinia 实例重复挂载
let storageListenerAttached = false

/** 会话列表 + 本地持久化（仅元数据，消息全文由后端持有） */
export const useConversationsStore = defineStore('conversations', () => {
  const items = ref<ConversationMeta[]>(
    sortByUpdatedAt(loadFromStorage<ConversationMeta[]>(STORAGE_KEY, [])),
  )

  function touchNow(): string {
    return new Date().toISOString()
  }

  function persist(): void {
    saveToStorage(STORAGE_KEY, items.value)
  }

  function reload(): void {
    items.value = sortByUpdatedAt(loadFromStorage<ConversationMeta[]>(STORAGE_KEY, []))
  }

  function add(item: ConversationMeta): void {
    items.value = sortByUpdatedAt([
      item,
      ...items.value.filter((existing) => existing.conversation_id !== item.conversation_id),
    ])
    persist()
  }

  /** 续聊：刷新 updated_at 并置顶 */
  function touch(conversationId: string): void {
    const now = touchNow()
    items.value = sortByUpdatedAt(
      items.value.map((item) =>
        item.conversation_id === conversationId ? { ...item, updated_at: now } : item,
      ),
    )
    persist()
  }

  function remove(conversationId: string): void {
    items.value = items.value.filter((item) => item.conversation_id !== conversationId)
    persist()
  }

  function rename(conversationId: string, title: string): void {
    const now = touchNow()
    items.value = sortByUpdatedAt(
      items.value.map((item) =>
        item.conversation_id === conversationId ? { ...item, title, updated_at: now } : item,
      ),
    )
    persist()
  }

  function clear(): void {
    items.value = []
    removeFromStorage(STORAGE_KEY)
  }

  if (typeof window !== 'undefined' && !storageListenerAttached) {
    storageListenerAttached = true
    window.addEventListener('storage', (event) => {
      if (event.key === STORAGE_EVENT_KEY) reload()
    })
  }

  return { items, add, touch, remove, rename, clear, reload }
})
