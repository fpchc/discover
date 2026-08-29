/**
 * 登录令牌对持久化（纯逻辑，无 React 依赖）。
 * 令牌是会话凭据的唯一事实源：写 localStorage（`disf_` 前缀，对齐 CLAUDE.md 第 11 节），
 * 由 `lib/api.ts` 的请求拦截器统一读取并注入 `Authorization: Bearer <token>`；
 * 供 `stores/auth.ts` 在启动恢复 / 登录 / 登出时读写。
 * 访问令牌 + 刷新令牌成对存储：刷新轮换制下两者必须同步更新（只存 access 会丢会话）。
 * 禁止在组件 / hooks 内直接读写 localStorage。
 */
const TOKEN_KEY = 'disf_auth_token'
const REFRESH_TOKEN_KEY = 'disf_auth_refresh_token'

/** 读取已存访问令牌；无令牌 / 隐私模式（localStorage 抛错）返回 null */
export function readStoredToken(): string | null {
  try {
    const raw = localStorage.getItem(TOKEN_KEY)
    if (raw !== null && raw !== '') return raw
  } catch {
    // 隐私模式：降级为未登录
  }
  return null
}

/** 写入 / 清除访问令牌；null = 清除 */
export function writeStoredToken(token: string | null): void {
  try {
    if (token === null) {
      localStorage.removeItem(TOKEN_KEY)
    } else {
      localStorage.setItem(TOKEN_KEY, token)
    }
  } catch (error) {
    console.warn('[discover][auth] 令牌写入失败，降级为内存态', error)
  }
}

/** 读取已存刷新令牌；无令牌 / 隐私模式返回 null */
export function readStoredRefreshToken(): string | null {
  try {
    const raw = localStorage.getItem(REFRESH_TOKEN_KEY)
    if (raw !== null && raw !== '') return raw
  } catch {
    // 隐私模式：降级为未登录
  }
  return null
}

/** 写入 / 清除刷新令牌；null = 清除 */
export function writeStoredRefreshToken(token: string | null): void {
  try {
    if (token === null) {
      localStorage.removeItem(REFRESH_TOKEN_KEY)
    } else {
      localStorage.setItem(REFRESH_TOKEN_KEY, token)
    }
  } catch (error) {
    console.warn('[discover][auth] 刷新令牌写入失败，降级为内存态', error)
  }
}

/** 当前令牌对快照（登出 / 401 过期等需要先读后清的场景） */
export interface StoredTokens {
  access: string | null
  refresh: string | null
}

/** 读取完整令牌对 */
export function loadTokens(): StoredTokens {
  return { access: readStoredToken(), refresh: readStoredRefreshToken() }
}

/** 一键清除令牌对（登出 / 会话过期共用） */
export function clearStoredTokens(): void {
  writeStoredToken(null)
  writeStoredRefreshToken(null)
}
