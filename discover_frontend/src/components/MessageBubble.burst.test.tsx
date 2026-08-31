import { act, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MessageBubble } from '@/components/MessageBubble'
import { useChatStore } from '@/stores/chat'

/**
 * 连续突发流式复现：模拟后端 message 帧持续到达（无 idle 间隙），
 * 观察正文是否在 message_end 之前就出现中间内容。
 * 若渲染被持续增量饿死 → 正文冻结为空，仅 message_end 后整块出现。
 */

function StreamedMessageList() {
  const messages = useChatStore((s) => s.activeMessages)
  return (
    <div>
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} onRetry={() => {}} />
      ))}
    </div>
  )
}

const BODY_TEXT = (): string => document.body.textContent ?? ''

afterEach(() => {
  useChatStore.getState().reset()
  vi.useRealTimers()
})

describe('连续突发流式（无 idle 间隙）', () => {
  it('突发正文增量后，揭示推进即应出现中间内容', () => {
    vi.useFakeTimers()
    render(<StreamedMessageList />)

    act(() => {
      useChatStore.getState().beginTurn('调研公司')
    })
    act(() => {
      useChatStore.getState().startThinking()
      useChatStore.getState().appendThinking('分析中…')
    })

    // 突发一批 message 增量（模拟网络连续到达）
    act(() => {
      for (const chunk of ['您好', '！我', '是多', '智能', '体平', '台助', '手。']) {
        useChatStore.getState().appendDelta(chunk)
      }
    })

    // 推进节流计时器（40ms），节流值应更新到最新
    act(() => {
      vi.advanceTimersByTime(40)
    })
    // 再给 scheduler 一轮机会（deferred 渲染若依赖计时器）
    act(() => {
      vi.advanceTimersByTime(40)
    })

    // 正文中间内容应已出现（而非整块输出）
    expect(BODY_TEXT()).toContain('您好')
  })
})
