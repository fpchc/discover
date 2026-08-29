import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UsagePage } from '@/components/UsagePage'
import { fetchAccountUsage, fetchUsageDaily } from '@/lib/api'

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    fetchAccountUsage: vi.fn(),
    fetchUsageDaily: vi.fn(),
  }
})

// echarts 需要 canvas，jsdom 不渲染真实图表，桩为无渲染占位
vi.mock('@/components/ui/chart', () => ({
  Chart: () => null,
}))

const daily = {
  account_id: '3f2a9c8e-0000-0000-0000-d1b4',
  name: '张三',
  days: 30,
  items: [
    {
      date: '2026-07-31',
      conversation_count: 1,
      message_count: 5,
      prompt_tokens: 100,
      completion_tokens: 50,
      total_tokens: 150,
      cached_read_tokens: 20,
      cached_write_tokens: 2,
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchAccountUsage).mockResolvedValue({
    account_id: '3f2a9c8e-0000-0000-0000-d1b4',
    name: '张三',
    conversation_count: 3,
    message_count: 10,
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    cached_read_tokens: 5,
    cached_write_tokens: 2,
  })
  vi.mocked(fetchUsageDaily).mockResolvedValue(daily)
})

describe('UsagePage 用量内容区', () => {
  it('渲染聚合指标卡（异步拉取后展示）', async () => {
    render(<UsagePage />)
    expect(await screen.findByText('总 Token')).toBeTruthy()
    expect(screen.getByText('消息数')).toBeTruthy()
    expect(screen.getByText('150')).toBeTruthy()
    expect(screen.getByText('输入 Token')).toBeTruthy()
    expect(screen.getByText('输出 Token')).toBeTruthy()
    expect(screen.getByText('缓存读 Token')).toBeTruthy()
    expect(screen.getByText('缓存写 Token')).toBeTruthy()
    expect(screen.getByText('会话数')).toBeTruthy()
  })

  it('聚合拉取失败时降级为骨架占位，不抛错', async () => {
    vi.mocked(fetchAccountUsage).mockRejectedValue(new Error('boom'))
    render(<UsagePage />)
    expect(screen.queryByText('总 Token')).toBeNull()
    expect(screen.queryByText('输入 Token')).toBeNull()
  })

  it('趋势接口正常时渲染趋势图卡片', async () => {
    render(<UsagePage />)
    expect(await screen.findByText('Token 用量趋势')).toBeTruthy()
    expect(screen.getByText('消息数趋势')).toBeTruthy()
    expect(screen.queryByText('趋势数据暂不可用')).toBeNull()
  })

  it('趋势接口失败时图区降级为提示', async () => {
    vi.mocked(fetchUsageDaily).mockRejectedValue(new Error('boom'))
    render(<UsagePage />)
    expect(await screen.findAllByText('趋势数据暂不可用')).toHaveLength(2)
  })

  it('趋势数据为空时展示空态提示', async () => {
    vi.mocked(fetchUsageDaily).mockResolvedValue({ ...daily, items: [] })
    render(<UsagePage />)
    expect(await screen.findAllByText('近 30 天暂无用量数据')).toHaveLength(2)
  })

  it('切换时间范围重新拉取趋势并更新文案（不写死近 30 天）', async () => {
    const user = userEvent.setup()
    render(<UsagePage />)
    // 默认近 30 天
    expect(await screen.findByText('近 30 天，按日堆叠（输入 / 输出）')).toBeTruthy()
    expect(fetchUsageDaily).toHaveBeenLastCalledWith(30)
    // 切到近 7 天 → 重新拉取 + 文案联动
    await user.click(screen.getByRole('button', { name: '近 7 天' }))
    expect(fetchUsageDaily).toHaveBeenLastCalledWith(7)
    expect(await screen.findByText('近 7 天，按日堆叠（输入 / 输出）')).toBeTruthy()
    expect(screen.getByText('近 7 天，每日消息量')).toBeTruthy()
  })
})
