import { useMemo } from 'react'
import type { StructuredParam } from '@/lib/structure'

/**
 * 结构化参数展示：把解析出的「【键】值」参数渲染为 KV 卡片网格 / 胶囊流，
 * 避免直接露出一串 【】 字符（视觉重构 —— 排版与信息层级优化）。
 * 纯展示组件，解析在父级 useMemo 完成，本组件不持有对话状态。
 *
 * - variant='grid'：带标题的分区卡片（用户输入的结构化参数，正文兜底在外部渲染）。
 * - variant='pills'：轻量胶囊流（AI 回复头部的参数摘要，跟随正文，不喧宾夺主）。
 * - max：超限折叠为「+N」，防止 AI 长回复参数列表撑爆布局。
 */
interface StructuredParamsProps {
  params: StructuredParam[]
  variant?: 'grid' | 'pills'
  /** grid 变体区块标题（如「输入参数」） */
  title?: string
  /** 最多展示条数（超出折叠） */
  max?: number
}

export function StructuredParams({
  params,
  variant = 'grid',
  title,
  max = 6,
}: StructuredParamsProps) {
  const shown = useMemo(() => params.slice(0, max), [params, max])
  const hidden = params.length - shown.length

  if (params.length === 0) return null

  if (variant === 'pills') {
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        {shown.map((param) => (
          <span
            key={param.key}
            title={param.value}
            className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-surface-2/80 px-2.5 py-1 text-xs"
          >
            <span className="flex-shrink-0 font-medium text-brand-2">{param.key}</span>
            <span className="truncate text-text-2">{param.value}</span>
          </span>
        ))}
        {hidden > 0 && (
          <span className="rounded-full border border-border bg-surface-2/80 px-2.5 py-1 font-mono text-xs text-text-3">
            +{hidden}
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="glass-surface rounded-xl border border-border p-3 shadow-card">
      {title !== undefined && (
        <p className="mb-2 flex items-center gap-1.5 px-0.5 font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-text-3">
          <span
            className="inline-block h-1.5 w-1.5 border border-brand-2/70 bg-brand-2/20"
            aria-hidden="true"
          />
          {title}
          <span className="ml-auto font-normal text-text-3">
            {shown.length}
            {hidden > 0 ? `+${hidden}` : ''}
          </span>
        </p>
      )}
      <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {shown.map((param) => (
          <div
            key={param.key}
            className="rounded-lg border border-border bg-surface-1/70 px-3 py-2 shadow-card"
          >
            <dt className="flex items-center gap-1.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-brand-2">
              <span className="h-1 w-1 rounded-full bg-brand-2 shadow-[0_0_6px_currentColor]" />
              {param.key}
            </dt>
            <dd className="mt-1 whitespace-pre-wrap break-words text-[13px] leading-relaxed text-text-1">
              {param.value}
            </dd>
          </div>
        ))}
        {hidden > 0 && (
          <div className="flex items-center justify-center rounded-lg border border-dashed border-border px-3 py-2 font-mono text-xs text-text-3">
            +{hidden} 项
          </div>
        )}
      </dl>
    </div>
  )
}
