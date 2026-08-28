/**
 * 结构化参数解析（纯函数，无副作用）。
 *
 * 痛点：用户输入的大段文本（如「【产品】xxx\n【目标行业】yyy」）与 AI 报告头部的
 * 参数段，原始形态像记事本堆砌（一堆 【】 字符），破坏界面的高级感。
 * 渲染层据此把参数解析为标签卡片 / KV 网格（见 components/StructuredParams.tsx），
 * 避免直接露出一串 【】。
 *
 * 规则（保守启发式，宁可降级为普通文本）：
 * - 键为单行 【键】；值取到下一个 【 或字符串末尾（保留内部换行，首尾修剪）。
 * - extractStructuredParams：解析全文所有参数块（用户输入用，≥2 块判定结构化）。
 * - extractLeadingParams：仅解析从正文开头连续出现的参数块（AI 回复头部摘要用，
 *   ≥2 块且覆盖开头才判定结构化，剥离后剩余正文继续走 Markdown）。
 */

/** 单条解析出的参数（【键】值） */
export interface StructuredParam {
  /** 【】 内键名（修剪后） */
  key: string
  /** 键对应的值（首尾修剪，保留内部换行） */
  value: string
  /** 原始匹配片段（含【】），用于从原文剥离 */
  raw: string
}

/** 匹配单个参数块：键为单行，值为惰性匹配直到值终止边界 */
const PARAM_BLOCK_RE = /【([^】\n]+)】([\s\S]*?)(?=\n\s*\n|【|$)/g

/**
 * 在文本 from 位置起找值终止位置：取「下一个【 / 空行 / 串尾」三者的最早处。
 * 空行终止保证头部参数段不吞并后续正文。注意 String#search 无起始位置参数，
 * 需在切片上执行后补偿偏移。
 */
function findValueEnd(text: string, from: number): number {
  const nextOpen = text.indexOf('【', from)
  const blankMatch = /\n\s*\n/.exec(text.slice(from))
  const blankLine = blankMatch === null ? -1 : blankMatch.index + from
  return Math.min(
    text.length,
    nextOpen === -1 ? text.length : nextOpen,
    blankLine === -1 ? text.length : blankLine,
  )
}

/** 解析文本中所有 【键】值 参数块（任意位置） */
export function extractStructuredParams(text: string): StructuredParam[] {
  const params: StructuredParam[] = []
  for (const match of text.matchAll(PARAM_BLOCK_RE)) {
    const key = match[1].trim()
    if (key === '') continue
    params.push({ key, value: match[2].trim(), raw: match[0] })
  }
  return params
}

/** 从开头剥离参数块的结果 */
export interface LeadingParams {
  /** 从正文开头连续解析出的参数块（可能为空） */
  params: StructuredParam[]
  /** 剥离头部参数块后的剩余正文（trimmed；无块时等于原文） */
  rest: string
  /** 是否判定为「结构化头部」：连续块 ≥ 2 且覆盖正文开头 */
  structured: boolean
}

/** 仅解析从正文开头（允许前导空白）连续出现的参数块 */
export function extractLeadingParams(text: string): LeadingParams {
  const start = text.search(/\S/)
  if (start === -1) return { params: [], rest: '', structured: false }

  const params: StructuredParam[] = []
  let index = start
  while (index < text.length) {
    // 当前位置必须正好是下一块开头，否则参数段到此结束（不连续 → 视为普通正文）
    const openMatch = text.slice(index).match(/^【([^】\n]+)】/)
    if (openMatch === null) break
    const key = openMatch[1].trim()
    if (key === '') break
    const valueEnd = findValueEnd(text, index + openMatch[0].length)
    params.push({
      key,
      value: text.slice(index + openMatch[0].length, valueEnd).trim(),
      raw: text.slice(index, valueEnd),
    })
    index = valueEnd
  }

  return { params, rest: text.slice(index).trim(), structured: params.length >= 2 }
}

/** 从原文中剥离全部参数块，返回剩余文本（用于参数卡片下方兜底展示未覆盖内容） */
export function stripParamBlocks(text: string, params: StructuredParam[]): string {
  let out = text
  for (const param of params) {
    out = out.replace(param.raw, ' ')
  }
  return out.trim()
}
