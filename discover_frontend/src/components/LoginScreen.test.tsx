import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LoginScreen from '@/components/LoginScreen'
import { login as apiLogin, fetchMe } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import type { AccountRecord } from '@/types'

vi.mock('@/lib/api', () => ({
  fetchMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}))
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), warning: vi.fn(), success: vi.fn() },
}))

const account: AccountRecord = {
  account_id: '3f2a9c8e-0000-0000-0000-d1b4',
  name: '张三',
  phone: '13800138001',
  avatar: null,
  status: 'active',
  is_system: false,
  created_at: '2026-08-28T00:00:00Z',
  last_login_at: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  useAuthStore.setState({ status: 'unauthenticated', account: null, token: '' })
})

describe('LoginScreen', () => {
  it('渲染手机号 / 密码输入与登录按钮', () => {
    render(<LoginScreen />)
    expect(screen.getByLabelText('手机号')).toBeTruthy()
    expect(screen.getByLabelText('密码')).toBeTruthy()
    expect(screen.getByRole('button', { name: /登录/ })).toBeTruthy()
  })

  it('空手机号 / 密码提交 → 提示输入，不调登录接口', async () => {
    const user = userEvent.setup()
    render(<LoginScreen />)
    await user.click(screen.getByRole('button', { name: /登录/ }))
    expect(toast.warning).toHaveBeenCalledWith('请输入手机号和密码')
    expect(apiLogin).not.toHaveBeenCalled()
  })

  it('填写后提交 → 调登录并进入已登录', async () => {
    const user = userEvent.setup()
    vi.mocked(apiLogin).mockResolvedValue({
      account_id: account.account_id,
      token: 'jwt-new',
      refresh_token: 'refresh-new',
      expires_in: 86_400,
      name: '张三',
    })
    vi.mocked(fetchMe).mockResolvedValue(account)
    render(<LoginScreen />)
    await user.type(screen.getByLabelText('手机号'), '13800138001')
    await user.type(screen.getByLabelText('密码'), 'eda365123456')
    await user.click(screen.getByRole('button', { name: /登录/ }))
    await waitFor(() => {
      expect(apiLogin).toHaveBeenCalledWith({
        phone: '13800138001',
        password: 'eda365123456',
      })
    })
    expect(useAuthStore.getState().status).toBe('authenticated')
    expect(localStorage.getItem('disf_auth_token')).toBe('jwt-new')
    expect(toast.success).toHaveBeenCalledWith('登录成功')
  })

  it('登录失败 → 展示后端文案', async () => {
    const user = userEvent.setup()
    vi.mocked(apiLogin).mockRejectedValue({
      isAxiosError: true,
      response: { status: 401, data: { detail: '手机号或密码错误' } },
    })
    render(<LoginScreen />)
    await user.type(screen.getByLabelText('手机号'), '13800138001')
    await user.type(screen.getByLabelText('密码'), 'wrong-pass')
    await user.click(screen.getByRole('button', { name: /登录/ }))
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('手机号或密码错误')
    })
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })
})
