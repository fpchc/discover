import type { LucideIcon } from 'lucide-react'
import { Gauge, Loader2, User } from 'lucide-react'
import { lazy, Suspense } from 'react'
import { PageHeader } from '@/components/PageHeader'
import { cn } from '@/lib/utils'
import { useViewStore } from '@/stores/view'

// 个人信息 / 用量信息为次级视图，懒加载拆分（用量页含 echarts，避免进首屏主包）
const ProfilePage = lazy(() =>
  import('@/components/ProfilePage').then((module) => ({ default: module.ProfilePage })),
)
const UsagePage = lazy(() =>
  import('@/components/UsagePage').then((module) => ({ default: module.UsagePage })),
)

/** 次级页面 chunk 就绪前的占位（用量页 echarts 较重在后台加载） */
function PageLoading() {
  return (
    <div className="flex h-full min-w-0 items-center justify-center gap-2 text-[13px] text-text-3">
      <Loader2 className="h-4 w-4 animate-spin text-brand-2" />
      加载中…
    </div>
  )
}

interface UserCenterProps {
  onBack: () => void
}

/** 左导航菜单项（激活态品牌渐变高亮 + 左侧色条，复用侧栏激活样式） */
function NavButton({
  active,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean
  icon: LucideIcon
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors',
        active
          ? 'sidebar-active sidebar-active--bar font-medium text-text-1'
          : 'text-text-2 hover:bg-surface-hover hover:text-text-1',
      )}
    >
      <Icon className="h-4 w-4 flex-shrink-0" />
      {label}
    </button>
  )
}

/**
 * 用户中心（模仿 DeepSeek 开放平台布局）：左侧菜单列 + 右侧内容区。
 * - 左导航主区为「用量」，点选切换右侧内容（不切页面）；
 * - 「个人中心」单独置于左下角区域（border-t 分隔）；
 * - 右侧顶栏复用 PageHeader（返回对话 + 居中标题），内容区按菜单懒加载组件。
 */
export function UserCenter({ onBack }: UserCenterProps) {
  const centerTab = useViewStore((s) => s.centerTab)
  const setCenterTab = useViewStore((s) => s.setCenterTab)

  return (
    <div className="flex h-full min-h-0 min-w-0">
      {/* 左导航：菜单列（DeepSeek 风格） */}
      <aside className="flex w-[220px] flex-shrink-0 flex-col border-r border-border bg-surface-1">
        <div className="flex h-14 flex-shrink-0 items-center gap-2.5 border-b border-border px-4">
          <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-brand-gradient text-white">
            <User className="h-4 w-4" />
          </span>
          <h1 className="truncate text-[15px] font-semibold text-text-1">用户中心</h1>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4" aria-label="用户中心菜单">
          <NavButton
            active={centerTab === 'usage'}
            icon={Gauge}
            label="用量"
            onClick={() => setCenterTab('usage')}
          />
        </nav>

        {/* 个人中心：左下角单独区域（border-t 分隔） */}
        <div className="flex-shrink-0 border-t border-border p-3">
          <NavButton
            active={centerTab === 'profile'}
            icon={User}
            label="个人中心"
            onClick={() => setCenterTab('profile')}
          />
        </div>
      </aside>

      {/* 右内容区：顶栏 + 滚动内容 */}
      <main className="flex min-w-0 flex-1 flex-col">
        <PageHeader title={centerTab === 'profile' ? '个人信息' : '用量信息'} onBack={onBack} />
        <div className="flex-1 overflow-y-auto">
          <Suspense fallback={<PageLoading />}>
            {centerTab === 'profile' ? <ProfilePage /> : <UsagePage />}
          </Suspense>
        </div>
      </main>
    </div>
  )
}
