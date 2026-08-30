import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ThinkingPanel } from '@/components/ThinkingPanel'
import type { ChatMessage } from '@/types'

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'm-1',
    role: 'assistant',
    content: '回答',
    created_at: '2026-01-01T00:00:00Z',
    status: 'done',
    ...overrides,
  }
}

describe('ThinkingPanel', () => {
  it('done 态（历史/已结束）默认折叠，仅显示标题', () => {
    render(
      <ThinkingPanel message={makeMessage({ thinking: '推理过程', thinkingStatus: 'done' })} />,
    )
    expect(screen.getByText('深度思考')).toBeTruthy()
    expect(screen.queryByText('推理过程')).toBeNull()
  })

  it('点击头部展开思考内容，再点折叠', () => {
    render(
      <ThinkingPanel message={makeMessage({ thinking: '推理过程', thinkingStatus: 'done' })} />,
    )
    const header = screen.getByText('深度思考')
    fireEvent.click(header)
    expect(screen.getByText('推理过程')).toBeTruthy()
    fireEvent.click(header)
    expect(screen.queryByText('推理过程')).toBeNull()
  })

  it('streaming 分段 thinking_ended 不折叠（多段思考期间保持展开）', () => {
    render(
      <ThinkingPanel
        message={makeMessage({ thinking: '推理过程', thinkingStatus: 'done', status: 'streaming' })}
      />,
    )
    expect(screen.getByText('推理过程')).toBeTruthy()
  })

  it('streaming 进行中强制展开，点击头部不折叠（toggle 锁定）', () => {
    render(
      <ThinkingPanel
        message={makeMessage({
          thinking: '推理过程',
          thinkingStatus: 'thinking',
          status: 'streaming',
        })}
      />,
    )
    fireEvent.click(screen.getByText('深度思考'))
    expect(screen.getByText('推理过程')).toBeTruthy()
  })

  it('整轮结束后折叠并显示累计耗时', () => {
    render(
      <ThinkingPanel
        message={makeMessage({
          thinking: '推理过程',
          thinkingStatus: 'done',
          status: 'done',
          thinkingDurationMs: 2500,
        })}
      />,
    )
    expect(screen.queryByText('推理过程')).toBeNull()
    expect(screen.getByText('3 秒')).toBeTruthy()
  })
})
