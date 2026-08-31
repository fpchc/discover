import { act, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MessageBubble } from '@/components/MessageBubble'
import { useChatStore } from '@/stores/chat'

/**
 * 流式正文渲染链路验证（定位「思考有打字效果、正文整块输出」）。
 * 走真实链路：chat store → 订阅组件 → MessageBubble → useStreamReveal → Markdown。
 * 逐条喂 thinking_delta / message_delta 增量，
 * 观察正文是否随增量前进（若前端链路正常，正文应在 message_end 前就出现中间内容）。
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

const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** 等揭示（33ms/tick，~151 字/s）推进到全文落地（真实计时器，模拟生产节拍） */
async function flushRender(ms = 200): Promise<void> {
  await act(async () => {
    await delay(ms)
  })
}

afterEach(() => {
  useChatStore.getState().reset()
})

describe('MessageBubble 流式正文增量渲染', () => {
  it('流式期间正文随 message 增量逐段前进，而非整块输出', async () => {
    render(<StreamedMessageList />)

    // 用户问题 + 空助手消息
    act(() => {
      useChatStore.getState().beginTurn('调研成都派兹科技有限公司')
    })
    // 思考阶段：thinking_delta 增量（思考区应逐字前进）
    act(() => {
      useChatStore.getState().startThinking()
    })
    for (const chunk of ['正在分析', '目标公司…', '确定行业']) {
      act(() => {
        useChatStore.getState().appendThinking(chunk)
      })
      await flushRender()
    }
    await flushRender()
    expect(document.body.textContent).toContain('正在分析目标公司…确定行业')

    // 正文阶段：message 增量逐条喂入，message_end 之前正文就应出现中间内容
    act(() => {
      useChatStore.getState().appendDelta('您好！')
    })
    await flushRender()
    expect(document.body.textContent).toContain('您好！')

    act(() => {
      useChatStore.getState().appendDelta('您要调研的是成都派兹。')
    })
    await flushRender()
    expect(document.body.textContent).toContain('您要调研的是成都派兹。')
    expect(document.body.textContent).toContain('您好！')

    act(() => {
      useChatStore.getState().appendDelta('这是第三条增量。')
    })
    await flushRender()
    expect(document.body.textContent).toContain('这是第三条增量。')

    // 收尾：message_end → 完成态
    act(() => {
      useChatStore.getState().completeAssistant()
    })
    await flushRender()
    expect(document.body.textContent).toContain('已生成')
  })
})
