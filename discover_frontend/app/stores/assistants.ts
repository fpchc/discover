import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { AssistantInfo, AssistantRecord } from '@/api/types'

/**
 * 通用对话保留字（API.md §6.2：对应目录里的通用对话项），用于把会话切回通用对话。
 * 发送 agent_id=generic 等价于首轮走通用 / 续聊切回通用。
 */
export const GENERIC_ASSISTANT_ID = 'generic'

/**
 * 助手目录 + 当前选择状态（API.md §6）。
 * 本层只做纯状态变更，不发起 HTTP；目录拉取由 useChatStream.loadAssistants 编排。
 * 选择随下一次 /chat-messages 生效（首轮绑定 / 续聊切换），故每次发消息读 selectedId。
 */
export const useAssistantsStore = defineStore('assistants', () => {
  /** 用户可选的助手目录（GET /assistants；含专家 + 通用对话） */
  const catalog = ref<AssistantRecord[]>([])
  /** 当前选择（专家 id / generic；目录未加载前为空串，此时发消息不带 agent_id） */
  const selectedId = ref<string>('')
  const loading = ref<boolean>(false)

  function setLoading(value: boolean): void {
    loading.value = value
  }

  /** 写入目录；选择仍为空时落到默认「通用对话」 */
  function setCatalog(list: AssistantRecord[]): void {
    catalog.value = list
    if (selectedId.value === '' && list.some((item) => item.id === GENERIC_ASSISTANT_ID)) {
      selectedId.value = GENERIC_ASSISTANT_ID
    }
  }

  /** 用户显式选择（选择器 change；立即生效于下一次发送） */
  function select(id: string): void {
    selectedId.value = id
  }

  /** 回合结束回显：metadata.assistant → 选择器状态（缺失 = 新会话未绑定，保持现状） */
  function syncFromAssistant(assistant: AssistantInfo | undefined): void {
    if (assistant === undefined) return
    selectedId.value = assistant.id ?? GENERIC_ASSISTANT_ID
  }

  /** 打开历史会话：以会话绑定助手校准选择器（ConversationRecord.agent_id；未绑定 → 通用） */
  function syncFromConversation(agentId: string | null): void {
    selectedId.value = agentId ?? GENERIC_ASSISTANT_ID
  }

  /** 新建 / 删除当前会话：回到默认「通用对话」 */
  function resetForNewConversation(): void {
    selectedId.value = GENERIC_ASSISTANT_ID
  }

  return {
    catalog,
    selectedId,
    loading,
    setLoading,
    setCatalog,
    select,
    syncFromAssistant,
    syncFromConversation,
    resetForNewConversation,
  }
})
