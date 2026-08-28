/**
 * 登录令牌持久化（纯逻辑，无 React 依赖）。
 * 令牌是会话凭据的唯一事实源：写 localStorage（`disf_` 前缀，对齐 CLAUDE.md 第 11 节），
 * 由 `lib/api.ts` 的请求拦截器统一读取并注入 `Authorization: Bearer <token>`；
 * 供 `stores/auth.ts` 在启动恢复 / 登录 / 登出时读写。
 * 禁止在组件 / hooks 内直接读写 localStorage。
 */
const TOKEN_KEY = 'disf_auth_token'

/** 读取已存令牌；无令牌 / 隐私模式（localStorage 抛错）返回 null */
export function readStoredToken(): string | null {
  try {
    const raw = localStorage.getItem(TOKEN_KEY)
    if (raw !== null && raw !== '') return raw
  } catch {
    // 隐私模式：降级为未登录
  }
  return null
}

/** 写入 / 清除令牌；null = 登出清除 */
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
