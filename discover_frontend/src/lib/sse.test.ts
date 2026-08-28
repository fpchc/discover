import { describe, expect, it } from 'vitest'
import { createSseParser, parseFrameJson } from '@/lib/sse'
import type { SseStreamFrame } from '@/types'

describe('createSseParser', () => {
  it('按空行切帧并解析 data 行', () => {
    const parser = createSseParser()
    const frames = parser.push(
      'data: {"event":"message","answer":"hi"}\n\ndata: {"event":"ping"}\n\n',
    )
    expect(frames).toHaveLength(2)
    expect(frames[0]?.data).toBe('{"event":"message","answer":"hi"}')
    expect(frames[1]?.data).toBe('{"event":"ping"}')
  })

  it('兼容 CRLF 帧边界（\\r\\n\\r\\n）', () => {
    const parser = createSseParser()
    const frames = parser.push('data: {"a":1}\r\n\r\ndata: {"b":2}\r\n\r\n')
    expect(frames).toHaveLength(2)
    expect(parseFrameJson<{ b: number }>(frames[1]?.data ?? '')).toEqual({ b: 2 })
  })

  it('跨分片解析：帧被网络分片截断时缓存，补齐后产出', () => {
    const parser = createSseParser()
    expect(parser.push('data: {"event":"mes')).toHaveLength(0)
    expect(parser.push('sage"}\n\ndata: {"event":"ping"}\n\n')).toHaveLength(2)
  })

  it('同一分片内多个帧全部产出', () => {
    const parser = createSseParser()
    const frames = parser.push(
      'data: {"event":"message","answer":"a"}\n\ndata: {"event":"message","answer":"b"}\n\ndata: {"event":"message_end"}\n\n',
    )
    expect(frames).toHaveLength(3)
  })

  it('忽略无 data 行 / 空 data 的帧', () => {
    const parser = createSseParser()
    const frames = parser.push('event: ping\n\ndata:   \n\n')
    expect(frames).toHaveLength(0)
  })

  it('flush 产出尾部未以空行收尾的残余帧', () => {
    const parser = createSseParser()
    expect(parser.push('data: {"event":"error"}')).toHaveLength(0)
    const tail = parser.flush()
    expect(tail).toHaveLength(1)
    expect(tail[0]?.data).toBe('{"event":"error"}')
  })

  it('data 行可多行拼接（join 以 \\n）', () => {
    const parser = createSseParser()
    const frames = parser.push('data: line1\ndata: line2\n\n')
    expect(frames).toHaveLength(1)
    expect(frames[0]?.data).toBe('line1\nline2')
  })
})

describe('parseFrameJson', () => {
  it('合法 JSON 返回解析结果', () => {
    const parsed = parseFrameJson<SseStreamFrame>('{"event":"ping"}')
    expect(parsed).not.toBeNull()
    expect(parsed?.event).toBe('ping')
  })

  it('非法 JSON 返回 null（不抛错）', () => {
    expect(parseFrameJson('not-json')).toBeNull()
  })
})
