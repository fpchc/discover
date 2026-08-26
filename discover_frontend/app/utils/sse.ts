/**
 * SSE 帧解析原语（纯函数，叶子层）。
 * 契约（CLAUDE.md 第 5 节）：data: 行按空行切帧；帧内 JSON 的 event 字段判别类型。
 * 对话业务状态不进入本文件。
 */

export interface RawSseFrame {
  /** SSE 协议层 event 行（本契约不使用；JSON 内 event 字段才是判别依据） */
  event: string
  /** data 行负载（JSON 字符串） */
  data: string
}

const DATA_PREFIX = 'data:'
const EVENT_PREFIX = 'event:'

export interface SseParser {
  /** 喂入一段文本（网络分片），返回已完成的帧 */
  push(chunk: string): RawSseFrame[]
  /** 流结束：返回尾部未以空行收尾的残余帧 */
  flush(): RawSseFrame[]
}

function indexOfFrameBoundary(text: string): number {
  const lf = text.indexOf('\n\n')
  const crlf = text.indexOf('\r\n\r\n')
  if (lf === -1) return crlf
  if (crlf === -1) return lf
  return Math.min(lf, crlf)
}

function parseRawFrame(raw: string): RawSseFrame | null {
  const lines = raw
    .replace(/\r/g, '')
    .split('\n')
    .filter((line) => line.length > 0)
  const dataLines = lines
    .filter((line) => line.startsWith(DATA_PREFIX))
    .map((line) => line.slice(DATA_PREFIX.length).trimStart())
  if (dataLines.length === 0) return null
  const data = dataLines.join('\n')
  if (data.trim() === '') return null
  const eventLine = lines.find((line) => line.startsWith(EVENT_PREFIX))
  const event = eventLine ? eventLine.slice(EVENT_PREFIX.length).trim() : ''
  return { event, data }
}

function splitCompleteFrames(
  input: string,
  setRemaining: (remaining: string) => void,
): RawSseFrame[] {
  const frames: RawSseFrame[] = []
  let remaining = input
  let boundary = indexOfFrameBoundary(remaining)
  while (boundary !== -1) {
    const rawFrame = remaining.slice(0, boundary)
    const parsed = parseRawFrame(rawFrame)
    if (parsed !== null) frames.push(parsed)
    remaining = remaining.slice(boundary).replace(/^\r?\n\r?\n/, '')
    boundary = indexOfFrameBoundary(remaining)
  }
  setRemaining(remaining)
  return frames
}

export function createSseParser(): SseParser {
  let buffer = ''

  function split(): RawSseFrame[] {
    const frames = splitCompleteFrames(buffer, (remaining) => {
      buffer = remaining
    })
    return frames
  }

  return {
    push(chunk: string): RawSseFrame[] {
      buffer += chunk
      return split()
    },
    flush(): RawSseFrame[] {
      const frames = split()
      const tail = buffer.trim()
      if (tail.length > 0) {
        const parsed = parseRawFrame(tail)
        if (parsed !== null) frames.push(parsed)
        buffer = ''
      }
      return frames
    },
  }
}

/** 运行时边界：JSON.parse 反序列化，失败返回 null（配合收窄使用） */
export function parseFrameJson<T>(data: string): T | null {
  try {
    const parsed: unknown = JSON.parse(data)
    return parsed as T
  } catch {
    return null
  }
}
