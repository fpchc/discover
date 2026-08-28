import { useEffect, useRef } from 'react'
import type { ThemePreference } from '@/stores/theme'
import { useThemeStore } from '@/stores/theme'

export type { ThemePreference }

/**
 * 主题 hook（只读壳，状态收拢于 `stores/theme.ts`）。
 * 职责只剩两件：维护 `html.dark` class、监听 system 偏好随系统实时切换；
 * isDark / toggle 全局共享（登录页与 App 壳互斥挂载、根层 Toaster 常驻，统一消费同一 store）。
 * 组件只读取 isDark / 调用 toggle / setPreference，禁止直接改 document class。
 */
export interface UseThemeResult {
  preference: ThemePreference
  isDark: boolean
  setPreference: (next: ThemePreference) => void
  toggle: () => void
}

export function useTheme(): UseThemeResult {
  const preference = useThemeStore((s) => s.preference)
  const isDark = useThemeStore((s) => s.isDark)
  const setPreference = useThemeStore((s) => s.setPreference)
  const toggle = useThemeStore((s) => s.toggle)

  // 同步 html.dark class（color-scheme 由 CSS :root / html.dark 变量接管）
  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
  }, [isDark])

  // 跟踪最新 preference，供 system 变化监听读取（避免监听闭包过期）
  const preferenceRef = useRef<ThemePreference>(preference)
  useEffect(() => {
    preferenceRef.current = preference
  }, [preference])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handleChange = (): void => {
      if (preferenceRef.current === 'system') {
        useThemeStore.getState().setPreference('system')
      }
    }
    mq.addEventListener('change', handleChange)
    return () => mq.removeEventListener('change', handleChange)
  }, [])

  return { preference, isDark, setPreference, toggle }
}
