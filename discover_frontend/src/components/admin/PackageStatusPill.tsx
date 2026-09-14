import { cn } from '@/lib/utils'
import type { PackageStatus } from '@/types'

const STATUS_STYLES: Record<PackageStatus, { label: string; className: string }> = {
  draft: { label: '草稿', className: 'border-brand-2/30 bg-brand-2/10 text-brand-2' },
  published: {
    label: '已发布',
    className: 'border-success/30 bg-success/10 text-success',
  },
  archived: {
    label: '已归档',
    className: 'border-border bg-surface-2 text-text-3',
  },
}

/** 技能包状态胶囊（列表 / 详情共用） */
export function PackageStatusPill({ status }: { status: PackageStatus }) {
  const style = STATUS_STYLES[status]
  return (
    <span
      className={cn(
        'inline-flex h-[22px] items-center rounded-full border px-2.5 text-[11px] font-medium',
        style.className,
      )}
    >
      {style.label}
    </span>
  )
}
