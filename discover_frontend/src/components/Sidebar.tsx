import {
  LogOut,
  MessageSquare,
  Moon,
  PanelLeftClose,
  Plus,
  Sparkles,
  Sun,
  Trash2,
} from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { APP_ENV } from '@/env'
import { cn } from '@/lib/utils'
import type { AssistantRecord, ConversationRecord } from '@/types'

/**
 * 侧栏（Discover 原版视觉）：实心 surface-1 + 渐变品牌 logo + 渐变「新对话」钮（Ctrl K 徽标）
 * + 「技能与助手」专家列表 + 「最近对话」会话列表 + 底部主题 / 账号 / 环境徽标。
 * 桌面折叠 → 整条收起（width 0，原版行为），由主区顶栏按钮展开；移动端 → 抽屉滑出。
 * 纯展示 + 事件上报；「技能与助手」点选 = 新建绑定该专家的工作会话（由 App 编排）。
 * 粒度订阅：仅订阅 conversations.items / loading 与 assistants 切片，不订阅 activeMessages。
 */
interface SidebarProps {
  conversations: ConversationRecord[]
  activeId: string
  /** 列表加载中（首次拉取后端 GET /conversations） */
  loading: boolean
  /** 助手目录（专家，GET /assistants；渲染「技能与助手」） */
  assistants: AssistantRecord[]
  /** 助手目录加载中 */
  assistantLoading: boolean
  /** 当前选择的助手（专家 id / 'generic'；高亮「技能与助手」对应项） */
  selectedAssistantId: string
  /** 当前登录账号显示名（AuthGate 保证壳内已认证；未加载为 null） */
  accountName: string | null
  /** 当前登录账号手机号（hover 提示用） */
  accountPhone: string | null
  /** 当前登录账号头像完整 URL（无头像为 null；未加载为 null） */
  accountAvatar: string | null
  isDark: boolean
  onNew: () => void
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  /** 桌面折叠侧栏（App 持有 collapsed 状态） */
  onCollapse: () => void
  /** 点选专家助手 → 新建绑定该助手的工作会话 */
  onSelectAssistant: (id: string) => void
  /** 点击账号区 → 进入个人中心页（/profile） */
  onOpenProfile: () => void
  onToggleTheme: () => void
  /** 退出登录（清令牌并回到登录页） */
  onLogout: () => void
}

function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const sameDay = date.toDateString() === new Date().toDateString()
  const hh = `${date.getHours()}`.padStart(2, '0')
  const mm = `${date.getMinutes()}`.padStart(2, '0')
  if (sameDay) return `${hh}:${mm}`
  return `${date.getMonth() + 1}/${date.getDate()}`
}

export function Sidebar({
  conversations,
  activeId,
  loading,
  assistants,
  assistantLoading,
  selectedAssistantId,
  accountName,
  accountPhone,
  accountAvatar,
  isDark,
  onNew,
  onSelect,
  onDelete,
  onCollapse,
  onSelectAssistant,
  onOpenProfile,
  onToggleTheme,
  onLogout,
}: SidebarProps) {
  const accountInitial =
    accountName !== null && accountName !== '' ? accountName.trim().charAt(0) : '?'
  return (
    <aside className="glass-surface flex h-full min-w-0 flex-col border-r border-border shadow-card">
      <header className="flex flex-shrink-0 items-center justify-between px-4 pb-2.5 pt-4">
        <div className="flex items-center gap-2">
          <span className="flex h-[26px] w-[26px] items-center justify-center rounded-lg bg-brand-gradient text-white shadow-glow-brand">
            <Sparkles className="h-[15px] w-[15px]" />
          </span>
          <span className="text-base font-bold tracking-wide text-brand-gradient">Discover</span>
        </div>
        <button
          type="button"
          title="收起侧栏"
          onClick={onCollapse}
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-surface-hover hover:text-text-1"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </header>

      <div className="px-4 pb-3.5 pt-1.5">
        <button
          type="button"
          onClick={onNew}
          className="relative flex h-10 w-full cursor-pointer items-center justify-center gap-2 rounded-[10px] bg-brand-gradient font-semibold text-white shadow-glow-brand transition-all hover:-translate-y-px hover:brightness-105 hover:shadow-[0_8px_26px_rgba(109,93,251,0.5)]"
        >
          <Plus className="h-4 w-4" />
          新对话
          <kbd className="absolute right-3 rounded-md bg-white/15 px-[7px] py-0.5 text-[11px] font-medium text-white/85">
            Ctrl K
          </kbd>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden px-2.5 pb-3">
        <p className="sidebar-section">技能与助手</p>
        {assistantLoading ? (
          <div className="flex flex-col gap-0.5 px-1">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        ) : assistants.length > 0 ? (
          <ul className="flex flex-col gap-0.5">
            {assistants.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  title={item.description}
                  onClick={() => onSelectAssistant(item.id)}
                  className={cn(
                    'flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-surface-hover',
                    item.id === selectedAssistantId && 'sidebar-active',
                  )}
                >
                  <Sparkles className="h-3.5 w-3.5 flex-shrink-0 text-brand-2" />
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text-1">
                    {item.name}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        <p className="sidebar-section">最近对话</p>
        {loading ? (
          <div className="flex flex-col gap-0.5 px-1">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        ) : conversations.length === 0 ? (
          <p className="px-2.5 text-[13px] leading-relaxed text-text-3">暂无会话</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {conversations.map((item) => {
              const active = item.conversation_id === activeId
              return (
                <li
                  key={item.conversation_id}
                  className={cn(
                    'flex min-w-0 items-center rounded-lg transition-colors hover:bg-surface-hover',
                    active && 'sidebar-active sidebar-active--bar',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(item.conversation_id)}
                    className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-lg py-2 pl-2.5 pr-1.5 text-left"
                  >
                    <MessageSquare
                      className={cn(
                        'h-3.5 w-3.5 flex-shrink-0',
                        active ? 'text-brand-2' : 'text-text-2',
                      )}
                    />
                    <span
                      title={item.name}
                      className="min-w-0 flex-1 truncate text-[13px] text-text-1"
                    >
                      {item.name}
                    </span>
                    <span className="flex-shrink-0 whitespace-nowrap text-[11px] text-text-3">
                      {formatTime(item.updated_at)}
                    </span>
                  </button>
                  <button
                    type="button"
                    title="删除会话"
                    onClick={() => onDelete(item.conversation_id)}
                    className="mr-1.5 flex h-6 w-6 flex-shrink-0 cursor-pointer items-center justify-center rounded-md text-text-3 transition-colors hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <footer className="border-t border-border px-3 pb-3 pt-2.5">
        {/* 账号行：头像 + 显示名（点击打开个人资料弹窗）+ 环境徽标（仅 dev）+ 主题 / 退出（统一图标钮） */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenProfile}
            title="个人中心"
            className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-lg px-1 py-0.5 text-left transition-colors hover:bg-surface-hover"
          >
            {accountAvatar !== null ? (
              <img
                src={accountAvatar}
                alt="头像"
                className="h-8 w-8 flex-shrink-0 rounded-full object-cover"
              />
            ) : (
              <span
                className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-brand-gradient text-[12px] font-semibold text-white"
                title={accountPhone ?? accountName ?? ''}
              >
                {accountInitial}
              </span>
            )}
            <span
              title={accountName ?? '未登录'}
              className="min-w-0 flex-1 truncate text-[13px] font-medium text-text-1"
            >
              {accountName ?? '未登录'}
            </span>
          </button>
          {APP_ENV !== 'production' && (
            <span
              className="max-w-[56px] flex-shrink-0 truncate rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-3"
              title={`环境：${APP_ENV}`}
            >
              {APP_ENV}
            </span>
          )}
          <button
            type="button"
            title={isDark ? '切换为浅色模式' : '切换为深色模式'}
            onClick={onToggleTheme}
            className="flex h-8 w-8 flex-shrink-0 cursor-pointer items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-surface-hover hover:text-text-1"
          >
            {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button
            type="button"
            title="退出登录"
            onClick={onLogout}
            className="flex h-8 w-8 flex-shrink-0 cursor-pointer items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-surface-hover hover:text-text-1"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </footer>
    </aside>
  )
}
