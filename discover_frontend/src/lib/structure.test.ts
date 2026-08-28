import { describe, expect, it } from 'vitest'
import { extractLeadingParams, extractStructuredParams, stripParamBlocks } from '@/lib/structure'

describe('extractStructuredParams', () => {
  it('解析连续【键】值块', () => {
    const text = '【产品】智能温控器\n【目标行业】暖通空调\n【地区】华南'
    const params = extractStructuredParams(text)
    expect(params).toHaveLength(3)
    expect(params[0]).toMatchObject({ key: '产品', value: '智能温控器' })
    expect(params[1]).toMatchObject({ key: '目标行业', value: '暖通空调' })
    expect(params[2]).toMatchObject({ key: '地区', value: '华南' })
  })

  it('多行值保留内部换行', () => {
    const text = '【产品】\n温控器 A\n恒温阀 B\n【目标行业】暖通'
    const params = extractStructuredParams(text)
    expect(params[0].value).toBe('温控器 A\n恒温阀 B')
  })

  it('正文中夹杂的参数块同样可解析', () => {
    const text = '开始【产品】温控器\n后面【地区】华南'
    const params = extractStructuredParams(text)
    expect(params.map((p) => p.key)).toEqual(['产品', '地区'])
  })

  it('无【】块返回空数组', () => {
    expect(extractStructuredParams('普通文本')).toEqual([])
    expect(extractStructuredParams('')).toEqual([])
  })
})

describe('extractLeadingParams', () => {
  it('剥离开头连续参数块并返回剩余正文', () => {
    const text = '【产品】温控器\n【目标行业】暖通\n\n以下是详细分析……'
    const result = extractLeadingParams(text)
    expect(result.structured).toBe(true)
    expect(result.params).toHaveLength(2)
    expect(result.params[0].key).toBe('产品')
    expect(result.rest).toBe('以下是详细分析……')
  })

  it('允许前导空白', () => {
    const result = extractLeadingParams('\n\n【A】1【B】2\n正文')
    expect(result.structured).toBe(true)
    expect(result.params.map((p) => p.key)).toEqual(['A', 'B'])
  })

  it('不足两块不判定为结构化', () => {
    const result = extractLeadingParams('【产品】温控器\n补充说明')
    expect(result.structured).toBe(false)
    expect(result.params).toHaveLength(1)
  })

  it('参数块不在开头则视为普通正文', () => {
    const result = extractLeadingParams('先讲背景\n【产品】温控器')
    expect(result.structured).toBe(false)
    expect(result.params).toHaveLength(0)
  })

  it('空文本返回空结果', () => {
    expect(extractLeadingParams('')).toMatchObject({ params: [], rest: '', structured: false })
  })
})

describe('stripParamBlocks', () => {
  it('从原文中移除参数块并修剪剩余文本', () => {
    // 参数段与正文以空行分隔（值是参数语义边界，空行后视为正文）
    const text = '【产品】温控器\n【行业】暖通\n\n补充说明'
    const params = extractStructuredParams(text)
    expect(stripParamBlocks(text, params)).toBe('补充说明')
  })

  it('整段为参数时剩余为空', () => {
    const params = extractStructuredParams('【A】1【B】2')
    expect(stripParamBlocks('【A】1【B】2', params)).toBe('')
  })
})
