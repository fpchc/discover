import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AccountLayout } from '@/components/AccountLayout'
import { ProfilePage } from '@/components/ProfilePage'
import { UsagePage } from '@/components/UsagePage'
import { fetchAccountUsage, fetchAvatarConfig, fetchUsageDaily } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import type { AccountRecord } from '@/types'

// React.lazy 动态 chunk 在并行测试负载下解析可能超过默认 1s，放宽等待
const ASYNC_TIMEOUT = 5000

// 只桩掉数据拉取函数，保留 avatarUrl 等纯函数原实现
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    fetchAvatarConfig: vi.fn(),
    fetchAccountUsage: vi.fn(),
    fetchUsageDaily: vi.fn(),
  }
})

// echarts 需要 canvas，jsdom 不渲染真实图表，桩为无渲染占位
vi.mock('@/components/ui/chart', () => ({
  Chart: () => null,
}))

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

/** 断言当前路由路径（返回对话 / 跳转后停留位置） */
function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

function renderAccount(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<AccountLayout />}>
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/usage" element={<UsagePage />} />
        </Route>
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ status: 'authenticated', account, token: 'jwt-x' })
  vi.mocked(fetchAvatarConfig).mockResolvedValue({
    max_size_bytes: 2 * 1024 * 1024,
    allowed_extensions: ['png', 'jpg', 'jpeg', 'webp', 'gif'],
    max_dimension: 512,
    min_dimension: 32,
  })
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

describe('AccountLayout 账号页布局（个人中心 / 用量独立路由）', () => {
  it('个人中心页（/profile）：左导航 + 个人信息内容', async () => {
    renderAccount('/profile')
    expect(screen.getByRole('heading', { name: '用户中心' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '个人中心' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '用量' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '个人信息' })).toBeTruthy()
    expect(
      await screen.findByRole('button', { name: '修改密码' }, { timeout: ASYNC_TIMEOUT }),
    ).toBeTruthy()
  })

  it('点击「用量」跳转 /usage 展示用量信息，再跳回个人中心', async () => {
    const user = userEvent.setup()
    renderAccount('/profile')
    await user.click(screen.getByRole('link', { name: '用量' }))
    expect(screen.getByRole('heading', { name: '用量信息' })).toBeTruthy()
    expect(await screen.findByText('总 Token', {}, { timeout: ASYNC_TIMEOUT })).toBeTruthy()
    await user.click(screen.getByRole('link', { name: '个人中心' }))
    expect(screen.getByRole('heading', { name: '个人信息' })).toBeTruthy()
    expect(
      await screen.findByRole('button', { name: '修改密码' }, { timeout: ASYNC_TIMEOUT }),
    ).toBeTruthy()
  })

  it('顶栏返回按钮 → 回对话页（/）', async () => {
    const user = userEvent.setup()
    renderAccount('/profile')
    await user.click(screen.getByTitle('返回对话'))
    expect(screen.getByTestId('location').textContent).toBe('/')
  })
})
