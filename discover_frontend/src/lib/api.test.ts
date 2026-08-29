import { describe, expect, it } from 'vitest'
import { avatarUrl } from '@/lib/api'

/**
 * avatarUrl：账号 avatar 存相对预览路径（/files/{id}/preview），拼上 API base；
 * 绝对地址直接透传；空值返回 null。
 */
describe('avatarUrl', () => {
  it('相对路径 → 拼上 API_BASE_URL', () => {
    expect(avatarUrl('/files/abc123/preview')).toBe('/api/v1/files/abc123/preview')
  })

  it('绝对地址 → 原样透传', () => {
    expect(avatarUrl('https://cdn.example.com/a.png')).toBe('https://cdn.example.com/a.png')
  })

  it('null / 空串 → null', () => {
    expect(avatarUrl(null)).toBeNull()
    expect(avatarUrl('')).toBeNull()
  })
})
