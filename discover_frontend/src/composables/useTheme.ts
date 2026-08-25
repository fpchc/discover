import { onScopeDispose, ref } from 'vue'

/**
 * 主题状态：light / dark / system（默认跟随系统，记忆于 localStorage `disf_theme`）。
 * 负责维护 `html.dark` class（index.html 已做首屏防 FOUC，本组合器在挂载后确认 / 覆盖）。
 * 组件只读取 isDark / 调用 toggle / setPreference，禁止直接改 document class。
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
    console.warn('[theme] 偏好写入失败，降级为内存态', error)
  }
}

function systemDark(): boolean {
  if (typeof window === 'undefined') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function useTheme() {
  const preference = ref<ThemePreference>(readPreference())
  const isDark = ref<boolean>(
    preference.value === 'dark' || (preference.value === 'system' && systemDark()),
  )

  function apply(): void {
    const root = typeof document === 'undefined' ? null : document.documentElement
    if (root !== null) {
      root.classList.toggle('dark', isDark.value)
    }
  }

  function setPreference(next: ThemePreference): void {
    preference.value = next
    writePreference(next)
    isDark.value = next === 'dark' || (next === 'system' && systemDark())
    apply()
  }

  /** 明暗一键切换：system 态先落到当前实际值再翻转，结果写为显式偏好 */
  function toggle(): void {
    setPreference(isDark.value ? 'light' : 'dark')
  }

  function handleSystemChange(): void {
    if (preference.value === 'system') {
      isDark.value = systemDark()
      apply()
    }
  }

  const mq =
    typeof window === 'undefined' ? null : window.matchMedia('(prefers-color-scheme: dark)')
  mq?.addEventListener('change', handleSystemChange)
  onScopeDispose(() => {
    mq?.removeEventListener('change', handleSystemChange)
  })

  apply()

  return { preference, isDark, setPreference, toggle }
}
