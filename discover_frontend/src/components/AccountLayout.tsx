import type { LucideIcon } from 'lucide-react'
import { Gauge, Loader2, User } from 'lucide-react'
import { Suspense } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { PageHeader } from '@/components/PageHeader'
import { cn } from '@/lib/utils'

/** 次级页面 chunk 就绪前的占位（用量页 echarts 较重在后台加载） */
function PageLoading() {
  return (
    <div className="flex h-full min-w-0 items-center justify-center gap-2 text-[13px] text-text-3">
      <Loader2 className="h-4 w-4 animate-spin text-brand-2" />
      加载中…
    </div>
  )
}

/** 左导航菜单项（激活态品牌渐变高亮 + 左侧色条，复用侧栏激活样式；NavLink 驱动路由跳转） */
function NavButton({ icon: Icon, label, to }: { icon: LucideIcon; label: string; to: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          'flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors',
          isActive
            ? 'sidebar-active sidebar-active--bar font-medium text-text-1'
            : 'text-text-2 hover:bg-surface-hover hover:text-text-1',
        )
      }
    >
      <Icon className="h-4 w-4 flex-shrink-0" />
      {label}
    </NavLink>
  )
}

/**
 * 账号页布局（模仿 DeepSeek 开放平台）：左导航列 + 右侧内容区。
 * 个人中心（/profile）与用量（/usage）为**独立页面路由**，共享本布局：左导航用 NavLink 跳转
 * （用量主区 + 左下角单独区域个人中心），内容区按 <Outlet/> 切换；布局实例不重挂，仅内容懒加载。
 * 右顶栏复用 PageHeader（返回对话 + 居中标题）。
 */
export function AccountLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const isUsage = location.pathname.startsWith('/usage')

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
          <NavButton icon={Gauge} label="用量" to="/usage" />
        </nav>

        {/* 个人中心：左下角单独区域（border-t 分隔） */}
        <div className="flex-shrink-0 border-t border-border p-3">
          <NavButton icon={User} label="个人中心" to="/profile" />
        </div>
      </aside>

      {/* 右内容区：顶栏 + 滚动内容 */}
      <main className="flex min-w-0 flex-1 flex-col">
        <PageHeader title={isUsage ? '用量信息' : '个人信息'} onBack={() => navigate('/')} />
        <div className="flex-1 overflow-y-auto">
          <Suspense fallback={<PageLoading />}>
            <Outlet />
          </Suspense>
        </div>
      </main>
    </div>
  )
}
