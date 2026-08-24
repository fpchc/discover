import { describe, expect, it } from 'vitest'
import { createSseParser, parseFrameJson } from './sse'

describe('createSseParser', () => {
  it('按空行切分完整帧', () => {
    const parser = createSseParser()
    const frames = parser.push(
      'data: {"event":"message","answer":"a"}\n\ndata: {"event":"ping"}\n\n',
    )
    expect(frames).toHaveLength(2)
    const first = frames[0]
    // 上方 toHaveLength(2) 已保证非空
    expect(parseFrameJson<{ event: string; answer: string }>(first!.data)).toEqual({
      event: 'message',
      answer: 'a',
    })
    const second = frames[1]
    expect(parseFrameJson<{ event: string }>(second!.data)).toEqual({ event: 'ping' })
  })

  it('跨网络分片累积缓冲', () => {
    const parser = createSseParser()
    expect(parser.push('data: {"event":"mess')).toHaveLength(0)
    const frames = parser.push('age","answer":"b"}\n\n')
    expect(frames).toHaveLength(1)
  })

  it('flush 处理无空行结尾的最后一帧', () => {
    const parser = createSseParser()
    expect(parser.push('data: {"event":"ping"}')).toHaveLength(0)
    const frames = parser.flush()
    expect(frames).toHaveLength(1)
  })

  it('忽略注释行与空 data', () => {
    const parser = createSseParser()
    const frames = parser.push(':comment\n\ndata:\n\n')
    expect(frames).toHaveLength(0)
  })

  it('非法 JSON 返回 null', () => {
    expect(parseFrameJson<unknown>('not-json')).toBeNull()
  })
})
