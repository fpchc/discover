import { cn } from '@/lib/utils'

/**
 * 状态徽章（视觉重构 —— AI 回复区域）：把流式阶段 / 终态渲染为高对比的小胶囊，
 * 带发光点，替代生硬的纯文字状态行。
 * 色板全部走主题令牌（--brand-* / --success / --destructive / --text-*），不硬编码。
 */
export type StatusBadgeTone = 'thinking' | 'generating' | 'done' | 'error' | 'stopped'

interface StatusBadgeProps {
  tone: StatusBadgeTone
  label: string
  /** 右侧副文案（如耗时，mono） */
  meta?: string
  /** 状态点呼吸发光（thinking / generating 用） */
  pulse?: boolean
}

const TONE_STYLES: Record<StatusBadgeTone, { badge: string; dot: string; glow: boolean }> = {
  thinking: {
    badge: 'border-brand-3/35 bg-brand-3/10 text-brand-2',
    dot: 'bg-brand-3',
    glow: true,
  },
  generating: {
    badge: 'border-brand-2/35 bg-brand-2/10 text-brand-2',
    dot: 'bg-brand-2',
    glow: true,
  },
  done: { badge: 'border-success/30 bg-success/10 text-success', dot: 'bg-success', glow: false },
  error: {
    badge: 'border-destructive/30 bg-destructive/10 text-destructive',
    dot: 'bg-destructive',
    glow: false,
  },
  stopped: { badge: 'border-border bg-surface-2 text-text-3', dot: 'bg-text-3', glow: false },
}

export function StatusBadge({ tone, label, meta, pulse = false }: StatusBadgeProps) {
  const style = TONE_STYLES[tone]
  return (
    <span
      className={cn(
        'inline-flex h-[22px] items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium',
        style.badge,
      )}
    >
      <span
        className={cn(
          'h-1.5 w-1.5 rounded-full',
          style.dot,
          (pulse || style.glow) && 'animate-pulse shadow-[0_0_6px_currentColor]',
        )}
        aria-hidden="true"
      />
      {label}
      {meta !== undefined && (
        <span className="font-mono text-[10px] font-normal text-text-3">{meta}</span>
      )}
    </span>
  )
}
