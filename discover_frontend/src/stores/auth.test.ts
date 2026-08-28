import { toast } from 'sonner'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { login as apiLogin, fetchMe } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import type { AccountRecord } from '@/types'

// 桩掉 api 层（axios 拦截器不在单测覆盖内）与 sonner（避免 jsdom 副作用）
vi.mock('@/lib/api', () => ({
  fetchMe: vi.fn(),
  login: vi.fn(),
}))
vi.mock('sonner', () => ({
  toast: { error: vi.fn(), warning: vi.fn(), success: vi.fn() },
}))

const TOKEN_KEY = 'disf_auth_token'

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
  // 登录 / 登出 / 过期均以「未登录」为现实前置态；resolveSession 测试各自覆盖
  useAuthStore.setState({ status: 'unauthenticated', account: null, token: '' })
})

describe('resolveSession（启动恢复）', () => {
  it('无本地令牌 → 未登录，不拉 /users/me', async () => {
    await useAuthStore.getState().resolveSession()
    const state = useAuthStore.getState()
    expect(state.status).toBe('unauthenticated')
    expect(state.account).toBeNull()
    expect(fetchMe).not.toHaveBeenCalled()
  })

  it('有令牌且 /users/me 通过 → 已登录', async () => {
    localStorage.setItem(TOKEN_KEY, 'jwt-ok')
    vi.mocked(fetchMe).mockResolvedValue(account)
    await useAuthStore.getState().resolveSession()
    const state = useAuthStore.getState()
    expect(state.status).toBe('authenticated')
    expect(state.token).toBe('jwt-ok')
    expect(state.account?.account_id).toBe(account.account_id)
  })

  it('有令牌但 /users/me 校验失败 → 回到未登录并清除令牌', async () => {
    localStorage.setItem(TOKEN_KEY, 'jwt-stale')
    vi.mocked(fetchMe).mockRejectedValue(new Error('401'))
    await useAuthStore.getState().resolveSession()
    const state = useAuthStore.getState()
    expect(state.status).toBe('unauthenticated')
    expect(state.account).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })
})

describe('login', () => {
  it('登录成功 → 写入令牌并进入已登录（账号取 /users/me 补充）', async () => {
    vi.mocked(apiLogin).mockResolvedValue({
      account_id: account.account_id,
      token: 'jwt-new',
      name: '张三',
    })
    vi.mocked(fetchMe).mockResolvedValue(account)
    const result = await useAuthStore.getState().login('13800138001', 'eda365123456')
    expect(result.ok).toBe(true)
    const state = useAuthStore.getState()
    expect(state.status).toBe('authenticated')
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt-new')
    expect(state.account?.account_id).toBe(account.account_id)
  })

  it('登录失败 → ok=false 并返回后端可读文案', async () => {
    vi.mocked(apiLogin).mockRejectedValue({
      isAxiosError: true,
      response: { status: 401, data: { detail: '手机号或密码错误' } },
    })
    const result = await useAuthStore.getState().login('13800138001', 'wrong-pass')
    expect(result.ok).toBe(false)
    expect(result.message).toBe('手机号或密码错误')
    expect(useAuthStore.getState().status).toBe('unauthenticated')
  })
})

describe('logout / expire', () => {
  it('logout → 回到未登录并清除令牌', () => {
    useAuthStore.setState({ status: 'authenticated', account, token: 'jwt-x' })
    localStorage.setItem(TOKEN_KEY, 'jwt-x')
    useAuthStore.getState().logout()
    const state = useAuthStore.getState()
    expect(state.status).toBe('unauthenticated')
    expect(state.account).toBeNull()
    expect(state.token).toBe('')
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })

  it('expire → 清状态并提示重新登录（仅已登录时生效）', () => {
    useAuthStore.setState({ status: 'authenticated', account, token: 'jwt-x' })
    localStorage.setItem(TOKEN_KEY, 'jwt-x')
    useAuthStore.getState().expire()
    const state = useAuthStore.getState()
    expect(state.status).toBe('unauthenticated')
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(toast.error).toHaveBeenCalledWith('登录已过期，请重新登录')
  })

  it('未登录时 expire 不重复弹提示', () => {
    useAuthStore.getState().expire()
    expect(toast.error).not.toHaveBeenCalled()
  })
})
