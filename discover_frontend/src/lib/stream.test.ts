import { describe, expect, it } from 'vitest'
import { resolveTurnEnd } from '@/lib/stream'

describe('resolveTurnEnd（v2 终态分流）', () => {
  it('status=succeeded → 正常完成', () => {
    expect(resolveTurnEnd({ status: 'succeeded' })).toBe('complete')
  })

  it('status=partial → 正常完成', () => {
    expect(resolveTurnEnd({ status: 'partial' })).toBe('complete')
  })

  it('status=cancelled（RunCancelled / 用户 stop）→ 停止语义', () => {
    expect(resolveTurnEnd({ status: 'cancelled' })).toBe('abort')
  })

  it('缺省 metadata（兼容旧版未回传 status）→ 正常完成', () => {
    expect(resolveTurnEnd({})).toBe('complete')
  })
})
