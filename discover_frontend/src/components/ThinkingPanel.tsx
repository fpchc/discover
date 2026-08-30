import { BrainCircuit, ChevronDown, LoaderCircle } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { ChatMessage } from '@/types'

/**
 * 思考分区（视觉重构 —— AI 回复区域）。
 * - 多段思考（思考→工具→再思考）追加同一分区；思考一旦开始，整轮流式期间保持展开，
 *   仅整轮结束（message_end / 停止）后折叠显示累计耗时，避免分段反复开合。
 * - 进行中：顶部粒子流（.particle-track）+ 头部 shimmer + 旋转指示；结束时折叠显示耗时。
 * - 头部按钮可折叠；进行中强制展开（toggle 锁定）。
 */
interface ThinkingPanelProps {
  message: ChatMessage
}

export function ThinkingPanel({ message }: ThinkingPanelProps) {
  const [expanded, setExpanded] = useState(false)
  const streaming = message.status === 'streaming'
  // 展开态由「整轮」决定而非分段：思考一旦开始，整轮流式期间保持展开；
  // 分段 thinking_ended 不折叠，仅 message_end / 停止后落到折叠态（避免多段思考反复开合）
  const hasThinking = message.thinkingStatus !== undefined
  const active = streaming && hasThinking
  const open = active || expanded

  function toggle(): void {
    if (active) return
    setExpanded((prev) => !prev)
  }

  function formatDuration(): string {
    const ms = message.thinkingDurationMs
    if (ms === undefined) return ''
    if (ms < 1000) return '不足 1 秒'
    return `${Math.round(ms / 1000)} 秒`
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface-2/50 shadow-card backdrop-blur-sm">
      {active && (
        <div className="particle-track border-b border-border/60 px-4" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
      )}
      <button
        type="button"
        onClick={toggle}
        className={cn(
          'flex w-full items-center gap-2 px-3 py-2 text-left',
          active && 'thinking-active-header',
        )}
      >
        <BrainCircuit className={cn('h-3.5 w-3.5', active ? 'text-brand-2' : 'text-text-3')} />
        <span className="text-[13px] font-medium text-text-2">深度思考</span>
        {active && <LoaderCircle className="ml-auto h-3.5 w-3.5 animate-spin text-brand-2" />}
        {!active && message.thinkingStatus === 'done' && (
          <span className="ml-auto font-mono text-xs text-text-3">{formatDuration()}</span>
        )}
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-text-3 transition-transform duration-200',
            open && 'rotate-180',
          )}
        />
      </button>
      {open && (
        <div className="whitespace-pre-wrap break-words border-t border-border px-3 py-2.5 text-[13px] leading-relaxed text-text-2">
          {message.thinking}
        </div>
      )}
    </div>
  )
}
