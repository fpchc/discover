import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProfilePage } from '@/components/ProfilePage'
import { fetchAvatarConfig } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import type { AccountRecord } from '@/types'

// 只桩掉数据拉取函数，保留 avatarUrl 等纯函数原实现
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    fetchAvatarConfig: vi.fn(),
  }
})

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

const AVATAR_CONFIG_TEXT = '头像：png/jpg/jpeg/webp/gif，≤2.0MB，边长 32~512px'

beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ status: 'authenticated', account, token: 'jwt-x' })
  vi.mocked(fetchAvatarConfig).mockResolvedValue({
    max_size_bytes: 2 * 1024 * 1024,
    allowed_extensions: ['png', 'jpg', 'jpeg', 'webp', 'gif'],
    max_dimension: 512,
    min_dimension: 32,
  })
})

describe('ProfilePage 个人中心内容区', () => {
  it('展示账号卡与只读账号信息，密码表单与头像约束不常驻', async () => {
    render(<ProfilePage />)
    // 账号卡 + 账号信息行各出现一次昵称/手机号
    expect(screen.getAllByText(account.name)).toHaveLength(2)
    expect(screen.getAllByText(account.phone)).toHaveLength(2)
    // 账号信息只读行（账号 ID 不展示）
    expect(screen.queryByText('账号 ID')).toBeNull()
    expect(screen.queryByText(account.account_id)).toBeNull()
    expect(screen.getByText('注册时间')).toBeTruthy()
    // 注册时间按本地时区格式化，只断言日期部分（跨时区稳定）
    expect(screen.getByText((content) => content.startsWith('2026-08-28'))).toBeTruthy()
    expect(screen.getByText('最近登录')).toBeTruthy()
    expect(screen.getByText('—')).toBeTruthy()
    // 修改密码只有入口按钮，表单默认收起
    expect(screen.getByRole('button', { name: '修改密码' })).toBeTruthy()
    expect(screen.queryByPlaceholderText('原密码')).toBeNull()
    // 头像约束文案默认不显示
    expect(screen.queryByText(AVATAR_CONFIG_TEXT)).toBeNull()
  })

  it('点击「修改密码」展开表单，再次点击收起', async () => {
    const user = userEvent.setup()
    render(<ProfilePage />)
    await user.click(screen.getByRole('button', { name: '修改密码' }))
    expect(screen.getByPlaceholderText('原密码')).toBeTruthy()
    expect(screen.getByPlaceholderText('确认新密码')).toBeTruthy()
    expect(screen.getByRole('button', { name: '收起修改' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '收起修改' }))
    expect(screen.queryByPlaceholderText('原密码')).toBeNull()
  })

  it('点击相机展开更换头像面板显示约束文案，取消后收起', async () => {
    const user = userEvent.setup()
    render(<ProfilePage />)
    expect(screen.queryByText(AVATAR_CONFIG_TEXT)).toBeNull()
    await user.click(screen.getByTitle('更换头像'))
    expect(await screen.findByText(AVATAR_CONFIG_TEXT)).toBeTruthy()
    expect(screen.getByRole('button', { name: '取消' })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByText(AVATAR_CONFIG_TEXT)).toBeNull()
  })
})
