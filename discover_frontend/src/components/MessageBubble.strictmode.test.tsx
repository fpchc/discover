import { act, render } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MessageBubble } from '@/components/MessageBubble'
import { useChatStore } from '@/stores/chat'

/**
 * StrictMode 回归（定位「正文整块输出」根因）。
 * useStreamReveal 的卸载清理若只 clearInterval 不清空 ref，开发期 effect 双调用后
 * timerRef 永久指向已失效的定时器 → 后续 effect 提前返回、揭示长度冻结在初值，
 * 正文直到 message_end 才整块出现。此用例在 StrictMode 下推进定时器，验证揭示能前进。
 */

function StreamedMessageList() {
  const messages = useChatStore((s) => s.activeMessages)
  return (
    <StrictMode>
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} onRetry={() => {}} />
      ))}
    </StrictMode>
  )
}

const BODY_TEXT = (): string => document.body.textContent ?? ''

afterEach(() => {
  useChatStore.getState().reset()
  vi.useRealTimers()
})

describe('StrictMode 下流式正文节流', () => {
  it('effect 双调用后节流定时器仍能推进，正文随增量逐段前进', () => {
    vi.useFakeTimers()
    render(<StreamedMessageList />)

    act(() => {
      useChatStore.getState().beginTurn('调研公司')
      useChatStore.getState().startThinking()
      useChatStore.getState().appendThinking('分析中…')
    })

    act(() => {
      useChatStore.getState().appendDelta('您好！')
    })
    act(() => {
      vi.advanceTimersByTime(40)
    })
    expect(BODY_TEXT()).toContain('您好！')

    act(() => {
      useChatStore.getState().appendDelta('我是助手。')
    })
    act(() => {
      vi.advanceTimersByTime(40)
    })
    expect(BODY_TEXT()).toContain('我是助手。')
  })
})
