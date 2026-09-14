import { describe, expect, it } from 'vitest'
import { errorCategoryLabel, formatPackageTime } from '@/lib/admin-packages'

describe('admin-packages helpers', () => {
  it('errorCategoryLabel 映射已知分类为中文文案', () => {
    expect(errorCategoryLabel('auth')).toBe('鉴权/令牌配置错误')
    expect(errorCategoryLabel('timeout')).toBe('执行超时')
    expect(errorCategoryLabel('script')).toBe('脚本执行错误')
  })

  it('errorCategoryLabel null 返回无', () => {
    expect(errorCategoryLabel(null)).toBe('无')
  })

  it('formatPackageTime 无效 ISO 原样返回', () => {
    expect(formatPackageTime('not-a-date')).toBe('not-a-date')
  })
})
