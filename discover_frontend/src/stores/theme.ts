import { create } from 'zustand'

/**
 * 主题状态（CLAUDE.md §3：跨组件共享状态一律走 Zustand）。
 * 单一事实源为 localStorage `disf_theme`；登录页 / App 壳 / 根层常驻 Toaster 共用本 store，
 * 任意一处 toggle 全局生效（根层 Toaster 必须跨登录态共享主题才能同步）。
 * `html.dark` class 由 `hooks/useTheme.ts` 订阅本 store 后同步。
 */
export type ThemePreference = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'disf_theme'

function readPreference(): ThemePreference {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw
  } catch {
    // 隐私模式：降级为跟随系统
  }
  return 'system'
}

function writePreference(value: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch (error) {
    console.warn('[discover][theme] 偏好写入失败，降级为内存态', error)
  }
}

/** system 偏好按当前系统主题解析为实际明暗 */
function resolveDark(preference: ThemePreference): boolean {
  return (
    preference === 'dark' ||
    (preference === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  )
}

export interface ThemeState {
  preference: ThemePreference
  isDark: boolean
  setPreference: (next: ThemePreference) => void
  toggle: () => void
}

const initialPreference = readPreference()

export const useThemeStore = create<ThemeState>((set, get) => ({
  preference: initialPreference,
  isDark: resolveDark(initialPreference),

  setPreference: (next) => {
    const isDark = resolveDark(next)
    // 同值 set 保持引用不变，避免无谓重渲
    set((state) =>
      state.preference === next && state.isDark === isDark ? state : { preference: next, isDark },
    )
    writePreference(next)
  },

  /** 明暗一键切换：system 态先落到当前实际值再翻转，结果写为显式偏好 */
  toggle: () => {
    const next: ThemePreference = get().isDark ? 'light' : 'dark'
    set({ preference: next, isDark: !get().isDark })
    writePreference(next)
  },
}))
