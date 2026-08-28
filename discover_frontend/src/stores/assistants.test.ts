import { beforeEach, describe, expect, it } from 'vitest'
import { GENERIC_ASSISTANT_ID, useAssistantsStore } from '@/stores/assistants'
import type { AssistantRecord } from '@/types'

const expert: AssistantRecord = {
  id: 'client-finder',
  type: 'expert',
  name: '客户查找',
  description: '查找客户',
  capabilities: ['client-finder'],
}

beforeEach(() => {
  useAssistantsStore.setState({ catalog: [], selectedId: '', loading: false })
})

describe('setCatalog', () => {
  it('目录含 generic 且选择为空时落到通用对话', () => {
    useAssistantsStore.getState().setCatalog([expert])
    expect(useAssistantsStore.getState().selectedId).toBe('')
    useAssistantsStore.getState().setCatalog([
      expert,
      {
        id: GENERIC_ASSISTANT_ID,
        type: 'generic',
        name: '通用对话',
        description: '',
        capabilities: [],
      },
    ])
    expect(useAssistantsStore.getState().selectedId).toBe(GENERIC_ASSISTANT_ID)
  })

  it('已有选择时不覆盖', () => {
    useAssistantsStore.getState().select('client-finder')
    useAssistantsStore.getState().setCatalog([expert])
    expect(useAssistantsStore.getState().selectedId).toBe('client-finder')
  })
})

describe('select / syncFromAssistant / syncFromConversation / reset', () => {
  it('select 立即生效', () => {
    useAssistantsStore.getState().select('client-finder')
    expect(useAssistantsStore.getState().selectedId).toBe('client-finder')
  })

  it('syncFromAssistant 回显回合助手（id 为 null → 通用）', () => {
    useAssistantsStore.getState().syncFromAssistant({ type: 'expert', id: 'client-finder' })
    expect(useAssistantsStore.getState().selectedId).toBe('client-finder')
    useAssistantsStore.getState().syncFromAssistant({ type: 'generic', id: null })
    expect(useAssistantsStore.getState().selectedId).toBe(GENERIC_ASSISTANT_ID)
  })

  it('syncFromAssistant 缺失时保持现状', () => {
    useAssistantsStore.getState().select('client-finder')
    useAssistantsStore.getState().syncFromAssistant(undefined)
    expect(useAssistantsStore.getState().selectedId).toBe('client-finder')
  })

  it('syncFromConversation 以会话绑定助手校准（未绑定 → 通用）', () => {
    useAssistantsStore.getState().syncFromConversation('client-finder')
    expect(useAssistantsStore.getState().selectedId).toBe('client-finder')
    useAssistantsStore.getState().syncFromConversation(null)
    expect(useAssistantsStore.getState().selectedId).toBe(GENERIC_ASSISTANT_ID)
  })

  it('resetForNewConversation 回到通用对话', () => {
    useAssistantsStore.getState().select('client-finder')
    useAssistantsStore.getState().resetForNewConversation()
    expect(useAssistantsStore.getState().selectedId).toBe(GENERIC_ASSISTANT_ID)
  })
})
