import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  onBack: () => void
  /** 顶栏右侧动作区（可为空，用于左右对称占位） */
  trailing?: ReactNode
}

/**
 * 次级页面（个人信息 / 用量信息）共用顶栏：左侧「返回」钮 + 居中标题 + 右侧动作区。
 * 高度与边距对齐 ChatWindow 顶栏（h-14），保证主区切换视觉一致。
 */
export function PageHeader({ title, onBack, trailing }: PageHeaderProps) {
  return (
    <header className="flex h-14 flex-shrink-0 items-center gap-2.5 px-4">
      <button
        type="button"
        title="返回对话"
        onClick={onBack}
        className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-text-2 transition-colors hover:bg-surface-hover hover:text-text-1"
      >
        <ArrowLeft className="h-[18px] w-[18px]" />
      </button>
      <h1 className="flex-1 truncate text-center text-[15px] font-semibold text-text-1">{title}</h1>
      <div className="flex h-8 w-8 items-center justify-center">{trailing}</div>
    </header>
  )
}
