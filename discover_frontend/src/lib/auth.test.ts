import { beforeEach, describe, expect, it } from 'vitest'
import { readStoredToken, writeStoredToken } from '@/lib/auth'

const TOKEN_KEY = 'disf_auth_token'

beforeEach(() => {
  localStorage.clear()
})

describe('readStoredToken', () => {
  it('无令牌返回 null', () => {
    expect(readStoredToken()).toBeNull()
  })

  it('读到已存令牌', () => {
    localStorage.setItem(TOKEN_KEY, 'jwt-abc')
    expect(readStoredToken()).toBe('jwt-abc')
  })

  it('空字符串按无令牌处理', () => {
    localStorage.setItem(TOKEN_KEY, '')
    expect(readStoredToken()).toBeNull()
  })
})

describe('writeStoredToken', () => {
  it('写入后 readStoredToken 读回', () => {
    writeStoredToken('jwt-xyz')
    expect(localStorage.getItem(TOKEN_KEY)).toBe('jwt-xyz')
    expect(readStoredToken()).toBe('jwt-xyz')
  })

  it('null 清除令牌', () => {
    writeStoredToken('jwt-abc')
    writeStoredToken(null)
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(readStoredToken()).toBeNull()
  })
})
