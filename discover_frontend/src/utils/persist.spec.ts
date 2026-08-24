import { beforeEach, describe, expect, it } from 'vitest'
import { loadFromStorage, removeFromStorage, saveToStorage } from './persist'

describe('persist', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('写入并读取', () => {
    expect(saveToStorage('meta', { a: 1 })).toBe(true)
    expect(loadFromStorage<{ a: number }>('meta', { a: 0 })).toEqual({ a: 1 })
  })

  it('缺失 key 返回 fallback', () => {
    expect(loadFromStorage<number[]>('missing', [])).toEqual([])
  })

  it('损坏数据返回 fallback', () => {
    localStorage.setItem('disf_bad', '{oops')
    expect(loadFromStorage<unknown>('bad', null)).toBeNull()
  })

  it('remove 后读取 fallback', () => {
    saveToStorage<number>('gone', 1)
    removeFromStorage('gone')
    expect(loadFromStorage<number | null>('gone', null)).toBeNull()
  })
})
