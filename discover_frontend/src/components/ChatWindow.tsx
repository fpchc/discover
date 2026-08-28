import { Loader2, Menu, PanelLeftOpen, SquarePen } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect, useRef } from 'react'
import { EmptyState } from '@/components/EmptyState'
import { MessageBubble } from '@/components/MessageBubble'
import type { ChatMessage } from '@/types'

/**
 * 对话主区（Discover 原版视觉）：极简顶栏（移动端侧栏钮 / 折叠时桌面展开钮 + 居中会话标题
 * + 新对话）+ 空态（EmptyState）+ 消息流（turn 分组：用户 + 助手为一回合，回合间细线分隔）。
 * 消息流只读渲染 activeMessages（粒度订阅），MessageBubble 经 React.memo 隔离，
 * onRetry / canRegenerate 由 App 稳定注入，非流式消息不随增量重渲。
 */
interface ChatWindowProps {
  messages: ChatMessage[]
  /** 当前会话标题（空串 = 新对话） */
  title: string
  /** 桌面侧栏是否已折叠（折叠时顶栏显示展开图标） */
  sidebarCollapsed: boolean
  /** 历史消息加载中（切换会话时） */
  historyLoading: boolean
  /** 流式生成中（顶栏标题前脉冲点） */
  isStreaming: boolean
  onToggleSidebar: () => void
  /** 顶栏「新对话」 */
  onNew: () => void
  onRetry: () => void
}

/** 消息流 → turn 分组：按「用户 + 助手」两两成组，奇数条（作废残留）单独成组 */
function groupTurns(messages: ChatMessage[]): ChatMessage[][] {
  const turns: ChatMessage[][] = []
  for (let i = 0; i < messages.length; i += 2) {
    turns.push(messages.slice(i, i + 2))
  }
  return turns
}

export function ChatWindow({
  messages,
  title,
  sidebarCollapsed,
  historyLoading,
  isStreaming,
  onToggleSidebar,
  onNew,
  onRetry,
}: ChatWindowProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastTurnKeyRef = useRef<string | undefined>(undefined)

  // 打开会话 / 新回合：强制滚到最新；流式增量：仅当已在底部附近时保持钉住（不打扰向上回读）
  useEffect(() => {
    const el = scrollRef.current
    if (el === null) return
    const last = messages[messages.length - 1]
    const lastTurnKey = last?.id
    if (lastTurnKey !== lastTurnKeyRef.current) {
      lastTurnKeyRef.current = lastTurnKey
      el.scrollTop = el.scrollHeight
      return
    }
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 96
    if (nearBottom) el.scrollTop = el.scrollHeight
  }, [messages])

  const turns = groupTurns(messages)

  const renderTurns: ReactNode[] = turns.map((turn, index) => {
    const userMessage = turn[0]
    if (userMessage === undefined) return null
    const assistantMessage = turn[1]
    const lastIndex = turns.length - 1
    const canRegenerate = index === lastIndex && assistantMessage?.status === 'done'
    return (
      <div key={userMessage.id}>
        {index > 0 && <div className="turn-divider" aria-hidden="true" />}
        <div className="flex flex-col gap-5">
          <MessageBubble message={userMessage} onRetry={onRetry} canRegenerate={false} />
          {assistantMessage !== undefined && (
            <MessageBubble
              message={assistantMessage}
              onRetry={onRetry}
              canRegenerate={canRegenerate}
            />
          )}
        </div>
      </div>
    )
  })

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col">
      <header className="flex h-14 flex-shrink-0 items-center gap-2.5 px-4">
        {/* 移动端侧栏钮（<768px 生效） */}
        <button
          type="button"
          title="打开侧栏"
          onClick={onToggleSidebar}
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-text-2 transition-colors hover:bg-surface-hover hover:text-text-1 md:hidden"
        >
          <Menu className="h-[18px] w-[18px]" />
        </button>
        {/* 桌面折叠态展开钮（仅侧栏收起时显示） */}
        {sidebarCollapsed && (
          <button
            type="button"
            title="展开侧栏"
            onClick={onToggleSidebar}
            className="hidden h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-text-2 transition-colors hover:bg-surface-hover hover:text-text-1 md:flex"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        )}

        <div className="flex min-w-0 flex-1 items-center justify-center gap-2">
          {isStreaming && <span className="title-pulse" aria-hidden="true" />}
          <span className="truncate text-[15px] font-semibold text-text-1">
            {title || '新对话'}
          </span>
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            title="新对话 (Ctrl K)"
            onClick={onNew}
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-text-2 transition-colors hover:bg-surface-hover hover:text-text-1"
          >
            <SquarePen className="h-4 w-4" />
          </button>
        </div>
      </header>

      {historyLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <div className="flex items-center gap-2 text-[13px] text-text-3">
            <Loader2 className="h-4 w-4 animate-spin text-brand-2" />
            正在加载会话…
          </div>
        </div>
      ) : messages.length === 0 ? (
        <EmptyState />
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 pb-8 pt-4 sm:px-6">
          <div className="mx-auto flex max-w-[800px] flex-col">{renderTurns}</div>
        </div>
      )}
    </section>
  )
}
