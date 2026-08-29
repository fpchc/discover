import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearStoredTokens,
  loadTokens,
  readStoredRefreshToken,
  readStoredToken,
  writeStoredRefreshToken,
  writeStoredToken,
} from '@/lib/auth'

const TOKEN_KEY = 'disf_auth_token'
const REFRESH_TOKEN_KEY = 'disf_auth_refresh_token'

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

describe('readStoredRefreshToken', () => {
  it('无刷新令牌返回 null', () => {
    expect(readStoredRefreshToken()).toBeNull()
  })

  it('读到已存刷新令牌', () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, 'refresh-abc')
    expect(readStoredRefreshToken()).toBe('refresh-abc')
  })

  it('空字符串按无刷新令牌处理', () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, '')
    expect(readStoredRefreshToken()).toBeNull()
  })
})

describe('writeStoredRefreshToken', () => {
  it('写入后 readStoredRefreshToken 读回', () => {
    writeStoredRefreshToken('refresh-xyz')
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe('refresh-xyz')
    expect(readStoredRefreshToken()).toBe('refresh-xyz')
  })

  it('null 清除刷新令牌', () => {
    writeStoredRefreshToken('refresh-abc')
    writeStoredRefreshToken(null)
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull()
    expect(readStoredRefreshToken()).toBeNull()
  })
})

describe('loadTokens / clearStoredTokens（令牌对）', () => {
  it('成对读写并一键清除', () => {
    writeStoredToken('jwt-a')
    writeStoredRefreshToken('refresh-a')
    expect(loadTokens()).toEqual({ access: 'jwt-a', refresh: 'refresh-a' })
    clearStoredTokens()
    expect(loadTokens()).toEqual({ access: null, refresh: null })
    expect(readStoredToken()).toBeNull()
    expect(readStoredRefreshToken()).toBeNull()
  })
})
