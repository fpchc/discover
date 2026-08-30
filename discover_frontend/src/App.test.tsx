import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '@/App'
import { fetchConversations, fetchMessages } from '@/lib/api'
import { useAssistantsStore } from '@/stores/assistants'
import { useAuthStore } from '@/stores/auth'
import type { AccountRecord } from '@/types'

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

const account: AccountRecord = {
  account_id: '3f2a9c8e-0000-0000-0000-d1b4',
  name: '张三',
  phone: '13800138001',
  avatar: null,
  status: 'active',
  is_system: false,
  created_at: '2026-08-28T10:30:00Z',
  last_login_at: null,
}

/**
 * 应用路由冒烟渲染：确认路由表（/ 对话页、/conversations/:id 会话页、/profile 个人中心）
 * 在 MemoryRouter 下可挂载无异常。AuthGate 在壳外（main.tsx），本测试直接渲染路由表，
 * 登录态由 auth store 预置为 authenticated。
 */
describe('App 路由冒烟渲染', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({ status: 'authenticated', account, token: 'jwt-x' })
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

  it('渲染对话页（/）：欢迎语、平铺助手胶囊与输入区', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: /今天，想/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: '账期评估' })).toBeTruthy()
    expect(screen.getByPlaceholderText(/发送消息/)).toBeTruthy()
    expect(screen.getByText('内容由 AI 生成，请仔细甄别')).toBeTruthy()
  })

  it('个人中心为独立页面（/profile）：左导航 + 个人信息内容', async () => {
    render(
      <MemoryRouter initialEntries={['/profile']}>
        <App />
      </MemoryRouter>,
    )
    // AccountLayout / ProfilePage 为懒加载 chunk，等待其挂载后断言
    expect(await screen.findByRole('heading', { name: '用户中心' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '用量' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '个人中心' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '个人信息' })).toBeTruthy()
    expect(await screen.findByRole('button', { name: '修改密码' }, { timeout: 5000 })).toBeTruthy()
  })

  it('落地 / 恒为新对话空态，不自动打开任何历史会话（访问首页不再跳转旧会话）', async () => {
    // 列表非空也不自动跳转 / 加载历史：恢复上次会话由 URL 深链 /conversations/:id 承担
    vi.mocked(fetchConversations).mockResolvedValue([CONVERSATION])
    vi.mocked(fetchMessages).mockResolvedValue([MESSAGE])
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    // 首页始终为「新对话」空态，历史消息不出现
    expect(await screen.findByRole('heading', { name: /今天，想/ }, { timeout: 5000 })).toBeTruthy()
    expect(screen.queryByText('恢复后的回复内容')).toBeNull()
  })

  it('会话页（/conversations/:id）按 URL 参数打开会话并加载历史', async () => {
    vi.mocked(fetchConversations).mockResolvedValue([CONVERSATION])
    vi.mocked(fetchMessages).mockResolvedValue([MESSAGE])
    render(
      <MemoryRouter initialEntries={['/conversations/conv-restore']}>
        <App />
      </MemoryRouter>,
    )
    // URL 驱动的会话打开：历史消息正文渲染出来
    expect(await screen.findByText('恢复后的回复内容', {}, { timeout: 5000 })).toBeTruthy()
  })

  it('在会话页点击「新对话」回到 / 新对话空态，不再跳回旧会话页', async () => {
    vi.mocked(fetchConversations).mockResolvedValue([CONVERSATION])
    vi.mocked(fetchMessages).mockResolvedValue([MESSAGE])
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/conversations/conv-restore']}>
        <App />
      </MemoryRouter>,
    )
    // 会话历史加载完成
    expect(await screen.findByText('恢复后的回复内容', {}, { timeout: 5000 })).toBeTruthy()
    // 点击顶栏「新对话」
    await user.click(screen.getByTitle('新对话 (Ctrl K)'))
    // 回到新对话空态，旧会话消息清空（回归：曾因 store→URL 反向同步跳回旧会话页）
    expect(await screen.findByRole('heading', { name: /今天，想/ }, { timeout: 5000 })).toBeTruthy()
    expect(screen.queryByText('恢复后的回复内容')).toBeNull()
  })
})
