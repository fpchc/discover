import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import type { AssistantRecord } from '@/api/types'
import { GENERIC_ASSISTANT_ID, useAssistantsStore } from './assistants'

const catalog: AssistantRecord[] = [
  {
    id: 'discover',
    type: 'expert',
    name: '客户发现',
    description: '为电子信息产业链销售寻找潜在客户',
    capabilities: ['client-finder'],
  },
  {
    id: 'generic',
    type: 'generic',
    name: '通用对话',
    description: '日常问答与通用助手',
    capabilities: [],
  },
]

describe('assistants store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('setCatalog 写入目录，空选择时默认通用对话', () => {
    const store = useAssistantsStore()
    store.setCatalog(catalog)
    expect(store.catalog).toEqual(catalog)
    expect(store.selectedId).toBe(GENERIC_ASSISTANT_ID)
  })

  it('select 记录用户显式选择', () => {
    const store = useAssistantsStore()
    store.setCatalog(catalog)
    store.select('discover')
    expect(store.selectedId).toBe('discover')
  })

  it('syncFromAssistant 回显专家 / 通用，缺失时保持现状', () => {
    const store = useAssistantsStore()
    store.setCatalog(catalog)
    store.syncFromAssistant({ type: 'expert', id: 'discover' })
    expect(store.selectedId).toBe('discover')

    store.syncFromAssistant({ type: 'generic', id: null })
    expect(store.selectedId).toBe(GENERIC_ASSISTANT_ID)

    store.select('discover')
    store.syncFromAssistant(undefined)
    expect(store.selectedId).toBe('discover')
  })

  it('syncFromConversation 以会话绑定校准（未绑定 → 通用）', () => {
    const store = useAssistantsStore()
    store.syncFromConversation('discover')
    expect(store.selectedId).toBe('discover')
    store.syncFromConversation(null)
    expect(store.selectedId).toBe(GENERIC_ASSISTANT_ID)
  })

  it('resetForNewConversation 回到默认通用', () => {
    const store = useAssistantsStore()
    store.setCatalog(catalog)
    store.select('discover')
    store.resetForNewConversation()
    expect(store.selectedId).toBe(GENERIC_ASSISTANT_ID)
  })

  it('setLoading 状态写入', () => {
    const store = useAssistantsStore()
    store.setLoading(true)
    expect(store.loading).toBe(true)
    store.setLoading(false)
    expect(store.loading).toBe(false)
  })
})
