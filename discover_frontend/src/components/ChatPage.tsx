import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { ChatInput } from '@/components/ChatInput'
import { ChatWindow } from '@/components/ChatWindow'
import { Sidebar } from '@/components/Sidebar'
import { CHAT_QUERY_MAX } from '@/env'
import { useChatStream } from '@/hooks/useChatStream'
import { useTheme } from '@/hooks/useTheme'
import { avatarUrl } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAssistantsStore } from '@/stores/assistants'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'

/**
 * 对话页（路由 `/` 新对话、`/conversations/:conversationId` 打开指定会话）。
 * URL 是页面导航唯一事实源：
 * - 切换会话 / 新对话 → navigate 改 URL，本组件经「URL 参数变化」effect 打开或复位会话；
 * - 首条消息创建新会话 → store 获得 ID → 同步回 URL（replace，避免历史记录膨胀）；
 * - 落地 `/` 恒为新对话空态；恢复上次会话由 URL 深链 `/conversations/:id` 承担，
 *   不做「访问首页自动重开旧会话」（曾因 loadList 异步恢复在用户点「新对话」后晚到而误跳回旧会话）。
 * useChatStream 在本页挂载：离开对话页（切到账号页 / 登出）即卸载 → 自动 abort 流式
 * （performance.md §4，杜绝后台幽灵请求写脏状态）。
 */
export function ChatPage() {
  const theme = useTheme()
  const chatStream = useChatStream()
  const navigate = useNavigate()
  const params = useParams<{ conversationId: string }>()
  /** URL 中的会话 ID；空串 = 新对话 */
  const urlId = params.conversationId ?? ''

  // ---- chat 切片（消息流容器订阅） ----
  const activeMessages = useChatStore((s) => s.activeMessages)
  const conversationId = useChatStore((s) => s.conversationId)
  const isStreaming = useChatStore((s) => s.isStreaming)
  const loadingHistory = useChatStore((s) => s.loadingHistory)
  const chatReset = useChatStore((s) => s.reset)

  // ---- conversations 切片（侧栏订阅，不订阅 activeMessages） ----
  const conversationItems = useConversationsStore((s) => s.items)
  const conversationsLoading = useConversationsStore((s) => s.loading)
  const removeConversation = useConversationsStore((s) => s.remove)

  // ---- assistants 切片 ----
  const assistantCatalog = useAssistantsStore((s) => s.catalog)
  const assistantLoading = useAssistantsStore((s) => s.loading)
  const selectedAssistantId = useAssistantsStore((s) => s.selectedId)
  const selectAssistant = useAssistantsStore((s) => s.select)
  const resetAssistant = useAssistantsStore((s) => s.resetForNewConversation)

  // ---- auth 切片（仅账号展示与登出；登录态由 AuthGate 在壳外把关） ----
  const account = useAuthStore((s) => s.account)
  const logout = useAuthStore((s) => s.logout)

  /** 移动端侧边栏抽屉开关（<768px 生效） */
  const [sidebarOpen, setSidebarOpen] = useState(false)
  /** 桌面端侧栏折叠（≥768px 生效；折叠 = 64px 图标轨道） */
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  /** 上次生效的 URL 会话参数（只在其变化时驱动打开 / 复位，避免 store 复位反向重开） */
  const prevUrlIdRef = useRef<string | null>(null)
  /** 上次的 store 会话 ID（仅「空 → 真实 ID」的新建瞬间允许同步回 URL，防复位/切换反向跳转） */
  const prevConversationIdRef = useRef(conversationId)

  const activeTitle = useMemo<string>(() => {
    const current = conversationItems.find((item) => item.conversation_id === conversationId)
    return current?.name ?? ''
  }, [conversationItems, conversationId])

  // URL → store：URL 参数变化时打开对应会话；无参数（新对话）则复位消息区
  useEffect(() => {
    const prev = prevUrlIdRef.current
    prevUrlIdRef.current = urlId
    if (urlId === prev) return
    if (urlId === '') {
      chatReset()
      resetAssistant()
      return
    }
    void chatStream.openConversation(urlId)
  }, [urlId, chatStream, chatReset, resetAssistant])

  // store → URL：仅在「新会话创建」（conversationId 从空变为真实 ID）时同步回 URL（replace，不产生多余历史记录）。
  // 打开已有会话 / 新对话复位都由 URL 驱动（URL→store），此处不反向导航——否则复位瞬间 store 仍持旧 ID
  // 会误跳回刚点「新对话」前的会话页（bug：点击新对话一直跳回 /conversations/:id）。
  useEffect(() => {
    const prev = prevConversationIdRef.current
    prevConversationIdRef.current = conversationId
    if (prev === '' && conversationId !== '' && urlId !== conversationId) {
      navigate(`/conversations/${conversationId}`, { replace: true })
    }
  }, [conversationId, urlId, navigate])

  // 首次加载：拉会话列表 / 助手目录；URL 直开会话页时，列表就绪后对齐其绑定助手
  // （不做「落地 / 自动恢复上次会话」：恢复由 URL 深链承担，避免异步恢复晚到误跳回旧会话）
  useEffect(() => {
    void chatStream.loadList().then(() => {
      const currentUrlId = prevUrlIdRef.current
      if (currentUrlId !== '' && currentUrlId !== useChatStore.getState().conversationId) {
        // 列表就绪后对齐会话已绑定助手（URL 直开发生在列表就绪前，选择器默认通用）
        const record = useConversationsStore
          .getState()
          .items.find((item) => item.conversation_id === currentUrlId)
        useAssistantsStore.getState().syncFromConversation(record?.agent_id ?? null)
      }
    })
    void chatStream.loadAssistants()
  }, [chatStream])

  useEffect(() => {
    const handleGlobalShortcut = (event: KeyboardEvent): void => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        chatStream.cancel()
        chatReset()
        resetAssistant()
        setSidebarOpen(false)
        setSidebarCollapsed(false)
        navigate('/')
      }
    }
    window.addEventListener('keydown', handleGlobalShortcut)
    return () => window.removeEventListener('keydown', handleGlobalShortcut)
  }, [chatStream, chatReset, resetAssistant, navigate])

  const handleSend = useCallback(
    (text: string) => {
      void chatStream.send(text)
    },
    [chatStream],
  )

  const handleStop = useCallback(() => {
    chatStream.stop()
  }, [chatStream])

  const handleRetry = useCallback(() => {
    void chatStream.retry()
  }, [chatStream])

  /** 新对话：作废旧流 → 复位 store → 回 / */
  const handleNew = useCallback(() => {
    chatStream.cancel()
    chatReset()
    resetAssistant()
    setSidebarOpen(false)
    setSidebarCollapsed(false)
    navigate('/')
  }, [chatStream, chatReset, resetAssistant, navigate])

  /** 空态 / 侧栏「助手」点选：新建绑定该专家的会话（等价于工作模式新任务） */
  const handleStartAssistant = useCallback(
    (id: string) => {
      chatStream.cancel()
      chatReset()
      selectAssistant(id)
      setSidebarOpen(false)
      setSidebarCollapsed(false)
      navigate('/')
    },
    [chatStream, chatReset, selectAssistant, navigate],
  )

  /** 侧栏会话点选：URL 驱动打开（openConversation 由 URL 参数 effect 触发） */
  const handleSelect = useCallback(
    (id: string) => {
      setSidebarOpen(false)
      if (id !== urlId) navigate(`/conversations/${id}`)
    },
    [urlId, navigate],
  )

  const handleDelete = useCallback(
    async (id: string): Promise<void> => {
      const removed = await removeConversation(id)
      if (removed && id === urlId) {
        chatReset()
        resetAssistant()
        navigate('/')
      }
    },
    [removeConversation, urlId, chatReset, resetAssistant, navigate],
  )

  /** 头部侧栏钮：按断点分流——桌面折叠 / 移动抽屉 */
  const handleToggleSidebar = useCallback(() => {
    if (window.matchMedia('(max-width: 767px)').matches) {
      setSidebarOpen((prev) => !prev)
    } else {
      setSidebarCollapsed((prev) => !prev)
    }
  }, [])

  return (
    <div className="relative flex h-full overflow-hidden">
      <div className="chat-bg" aria-hidden="true" />

      <div
        className={cn(
          'sidebar-wrapper',
          sidebarCollapsed && 'is-collapsed',
          sidebarOpen && 'is-open',
        )}
      >
        <Sidebar
          conversations={conversationItems}
          activeId={conversationId}
          loading={conversationsLoading}
          assistants={assistantCatalog}
          assistantLoading={assistantLoading}
          selectedAssistantId={selectedAssistantId}
          accountName={account?.name ?? null}
          accountPhone={account?.phone ?? null}
          accountAvatar={account !== null ? avatarUrl(account.avatar) : null}
          isDark={theme.isDark}
          onNew={handleNew}
          onSelect={handleSelect}
          onDelete={handleDelete}
          onCollapse={() => setSidebarCollapsed(true)}
          onSelectAssistant={handleStartAssistant}
          onOpenProfile={() => {
            setSidebarOpen(false)
            navigate('/profile')
          }}
          onToggleTheme={theme.toggle}
          onLogout={logout}
        />
      </div>
      {sidebarOpen && (
        <button
          type="button"
          aria-label="关闭侧栏"
          className="mobile-mask"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <main className="relative z-10 flex min-w-0 flex-1 flex-col">
        <ChatWindow
          messages={activeMessages}
          title={activeTitle}
          sidebarCollapsed={sidebarCollapsed}
          historyLoading={loadingHistory}
          isStreaming={isStreaming}
          onToggleSidebar={handleToggleSidebar}
          onNew={handleNew}
          onRetry={handleRetry}
        />
        <div className="mx-auto w-full max-w-[860px] flex-shrink-0 px-4 pb-3.5 pt-1 sm:px-6">
          <ChatInput
            disabled={isStreaming}
            maxLength={CHAT_QUERY_MAX}
            assistants={assistantCatalog}
            selectedAssistantId={selectedAssistantId}
            onSend={handleSend}
            onStop={handleStop}
            onAssistantChange={selectAssistant}
          />
        </div>
      </main>
    </div>
  )
}
