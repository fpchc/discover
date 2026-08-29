import { toast } from 'sonner'
import { create } from 'zustand'
import { login as apiLogin, logout as apiLogout, fetchMe } from '@/lib/api'
import {
  clearStoredTokens,
  loadTokens,
  readStoredToken,
  writeStoredRefreshToken,
  writeStoredToken,
} from '@/lib/auth'
import { mapHttpError } from '@/lib/errors'
import { useAssistantsStore } from '@/stores/assistants'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import { useViewStore } from '@/stores/view'
import type { AccountRecord } from '@/types'

/**
 * 账号认证状态（ACCOUNT_API.md）：启动恢复会话 / 登录 / 登出 / 401 过期。
 * 令牌唯一事实源在 localStorage（lib/auth.ts），API 层拦截器自动注入 Bearer；
 * 本层只维护登录态（status / account）与编排，account 供 UI（侧栏账号区）展示。
 * 登出 / 过期必须重置 chat / conversations / assistants 三 store，
 * 防上一账号数据泄漏给下一登录（数据隔离红线，见 ACCOUNT_API.md §4）。
 */
export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface AuthState {
  /** loading = 启动恢复中；authenticated = 已登录；unauthenticated = 未登录 / 会话过期 */
  status: AuthStatus
  /** 当前登录账号；未登录 / 未拉取为 null */
  account: AccountRecord | null
  /** 内存中的当前令牌（与 localStorage 同步，供调试 / 后续使用） */
  token: string
  /** 启动时恢复：本地令牌 → 拉 GET /users/me 校验；无令牌 / 校验失败 → 未登录 */
  resolveSession: () => Promise<void>
  /** 登录：成功写入令牌并进入 authenticated；失败返回可读文案 */
  login: (phone: string, password: string) => Promise<{ ok: boolean; message?: string }>
  /** 资料更新（昵称 / 头像 / 密码）后同步账号展示（返回的 AccountRecord 全量替换） */
  applyAccount: (account: AccountRecord) => void
  /** 主动退出登录：清令牌并重置各 store */
  logout: () => void
  /** 401 会话过期：清状态 + 提示重新登录（由 api 层拦截器触发） */
  expire: () => void
}

/** 登出 / 过期时清空跨账号共享状态，防止上一账号数据泄漏（ACCOUNT_API.md §4） */
function resetAppState(): void {
  useChatStore.getState().reset()
  useConversationsStore.getState().replaceAll([])
  useConversationsStore.getState().setLoading(false)
  useAssistantsStore.getState().setCatalog([])
  useAssistantsStore.getState().resetForNewConversation()
  // 视图回对话页并写回 localStorage，新登录不残留上一账号停留的页面 / 会话
  useViewStore.getState().setView('chat')
  useViewStore.getState().setCenterTab('profile')
  useViewStore.getState().setSavedConversationId('')
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'loading',
  account: null,
  token: readStoredToken() ?? '',

  resolveSession: async () => {
    const token = readStoredToken()
    if (token === null) {
      set({ status: 'unauthenticated', token: '', account: null })
      return
    }
    set({ status: 'loading', token })
    try {
      const account = await fetchMe()
      set({ status: 'authenticated', token, account })
    } catch {
      // 令牌对无效 / 过期 / 账号不存在：清除并回到登录页（启动期不弹 toast）
      clearStoredTokens()
      set({ status: 'unauthenticated', token: '', account: null })
    }
  },

  login: async (phone, password) => {
    try {
      const res = await apiLogin({ phone, password })
      // 令牌对写入 localStorage：access 由拦截器注入，refresh 供 401 续期 / 登出作废（轮换制成对更新）
      writeStoredToken(res.token)
      writeStoredRefreshToken(res.refresh_token)
      // 先用登录响应拼基础账号（少一次串行往返）；随后 fetchMe 补充完整字段
      const base: AccountRecord = {
        account_id: res.account_id,
        name: res.name ?? phone,
        phone,
        avatar: null,
        status: 'active',
        is_system: false,
        created_at: new Date().toISOString(),
        last_login_at: null,
      }
      set({ status: 'authenticated', token: res.token, account: base })
      try {
        const account = await fetchMe()
        set({ account })
      } catch {
        // 补充拉取失败保持基础信息，不阻断使用（令牌已写入，数据接口可用）
      }
      return { ok: true }
    } catch (error) {
      return { ok: false, message: mapHttpError(error).message }
    }
  },

  applyAccount: (account) => {
    set({ account })
  },

  logout: () => {
    const { access, refresh } = loadTokens()
    // 先清本地再调后端：登出即时生效；后端作废走显式令牌，不依赖拦截器读 localStorage 时机
    clearStoredTokens()
    resetAppState()
    set({ status: 'unauthenticated', token: '', account: null })
    // 服务端作废令牌对（幂等：访问令牌已过期也返回 204）；失败不阻塞本地登出
    if (access !== null || refresh !== null) {
      void apiLogout(access, refresh).catch(() => {
        // 后端作废失败可忽略：本地令牌已清，服务端由 TTL 兜底
      })
    }
  },

  expire: () => {
    if (get().status !== 'authenticated') return
    clearStoredTokens()
    resetAppState()
    set({ status: 'unauthenticated', token: '', account: null })
    toast.error('登录已过期，请重新登录')
  },
}))
