import { render, screen } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/App'
import { fetchConversations, fetchMessages } from '@/lib/api'
import { useAssistantsStore } from '@/stores/assistants'
import { useViewStore } from '@/stores/view'

// 只桩掉会话列表 / 历史接口（恢复会话用例需要控制返回值）；loadAssistants 保持真实请求
// 在 jsdom 失败并被编排层静默捕获，不覆盖 beforeAll 预置的目录。
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    fetchConversations: vi.fn(),
    fetchMessages: vi.fn(),
  }
})

const CONVERSATION = {
  conversation_id: 'conv-restore',
  agent_id: null,
  model_provider: null,
  model_id: null,
  name: '恢复的对话',
  summary: null,
  status: 'active' as const,
  dialogue_count: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const MESSAGE = {
  message_id: 'msg-1',
  conversation_id: 'conv-restore',
  agent_id: null,
  query: '你好',
  answer: '恢复后的回复内容',
  thinking: null,
  status: 'normal' as const,
  error: null,
  latency_ms: 100,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

/**
 * 应用冒烟渲染：确认 React 树（App → 侧栏/主区/输入区 + Toaster）可挂载无异常。
 * 挂载期 loadAssistants 请求在 jsdom 失败会被编排层静默捕获，目录预置在 store（失败时保持）。
 */
describe('App 冒烟渲染', () => {
  // 视图 store 跨组件持有，每个用例复位为默认（对话页 + 个人中心菜单 + 无会话）
  beforeEach(() => {
    vi.clearAllMocks()
    useViewStore.setState({ view: 'chat', centerTab: 'profile', savedConversationId: '' })
    vi.mocked(fetchConversations).mockResolvedValue([])
    vi.mocked(fetchMessages).mockResolvedValue([])
  })

  beforeAll(() => {
    useAssistantsStore.setState({
      catalog: [
        {
          id: 'account-period',
          type: 'expert',
          name: '账期评估',
          description: '评估客户账期风险',
          capabilities: [],
        },
      ],
      selectedId: '',
      loading: false,
    })
  })

  it('渲染欢迎语、平铺助手胶囊与输入区', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: /今天，想/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: '账期评估' })).toBeTruthy()
    expect(screen.getByPlaceholderText(/发送消息/)).toBeTruthy()
    expect(screen.getByText('内容由 AI 生成，请仔细甄别')).toBeTruthy()
  })

  it('视图为用户中心时渲染用户中心布局（刷新停留当前页面）', async () => {
    useViewStore.setState({ view: 'center', centerTab: 'profile' })
    render(<App />)
    // UserCenter 懒加载 chunk，等待其挂载后断言左导航
    expect(await screen.findByRole('heading', { name: '用户中心' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '用量' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '个人中心' })).toBeTruthy()
  })

  it('刷新后恢复上次打开的会话（本地记录仍在会话列表时重开并加载历史）', async () => {
    useViewStore.setState({
      view: 'chat',
      centerTab: 'profile',
      savedConversationId: 'conv-restore',
    })
    vi.mocked(fetchConversations).mockResolvedValue([CONVERSATION])
    vi.mocked(fetchMessages).mockResolvedValue([MESSAGE])
    render(<App />)
    // 恢复的会话历史消息正文渲染出来
    expect(await screen.findByText('恢复后的回复内容', {}, { timeout: 5000 })).toBeTruthy()
  })
})
