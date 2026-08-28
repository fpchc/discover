import { beforeEach, describe, expect, it } from 'vitest'
import { useThemeStore } from '@/stores/theme'

const STORAGE_KEY = 'disf_theme'

beforeEach(() => {
  localStorage.clear()
})

describe('theme store', () => {
  it('无记忆偏好 → 跟随系统（jsdom matchMedia=false → 浅色）', () => {
    const state = useThemeStore.getState()
    expect(state.preference).toBe('system')
    expect(state.isDark).toBe(false)
  })

  it('setPreference → 更新偏好并记忆到 localStorage', () => {
    useThemeStore.getState().setPreference('dark')
    const state = useThemeStore.getState()
    expect(state.preference).toBe('dark')
    expect(state.isDark).toBe(true)
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark')
  })

  it('toggle：浅色 → 深色，再切回浅色', () => {
    useThemeStore.getState().setPreference('light')
    useThemeStore.getState().toggle()
    expect(useThemeStore.getState().isDark).toBe(true)
    expect(useThemeStore.getState().preference).toBe('dark')
    useThemeStore.getState().toggle()
    expect(useThemeStore.getState().isDark).toBe(false)
    expect(useThemeStore.getState().preference).toBe('light')
  })

  it('重复 setPreference 同值保持状态引用不变（不触发无谓重渲）', () => {
    useThemeStore.getState().setPreference('dark')
    const before = useThemeStore.getState()
    useThemeStore.getState().setPreference('dark')
    expect(useThemeStore.getState()).toBe(before)
  })
})
