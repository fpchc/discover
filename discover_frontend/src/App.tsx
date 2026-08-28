import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChatInput } from '@/components/ChatInput'
import { ChatWindow } from '@/components/ChatWindow'
import { Sidebar } from '@/components/Sidebar'
import { CHAT_QUERY_MAX } from '@/env'
import { useChatStream } from '@/hooks/useChatStream'
import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'
import { useAssistantsStore } from '@/stores/assistants'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'

/**
 * 应用壳层 + 页面编排（单页无路由，CLAUDE.md 第 1 节）。
 * - 粒度订阅各 store 切片（防坑点 3：侧栏不随流式重渲，见 performance.md §3）。
 * - 事件回调统一 useCallback 稳定引用，配合 MessageBubble 的 React.memo 隔离
 *   （performance.md §1：流式增量不触发非流式消息重渲）。
 * - 全局快捷键 Ctrl/Cmd+K 新建会话。
 */
export default function App() {
  const theme = useTheme()
  const chatStream = useChatStream()

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

  const activeTitle = useMemo<string>(() => {
    const current = conversationItems.find((item) => item.conversation_id === conversationId)
    return current?.name ?? ''
  }, [conversationItems, conversationId])

  useEffect(() => {
    void chatStream.loadList()
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
      }
    }
    window.addEventListener('keydown', handleGlobalShortcut)
    return () => window.removeEventListener('keydown', handleGlobalShortcut)
  }, [chatStream, chatReset, resetAssistant])

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

  const handleNew = useCallback(() => {
    chatStream.cancel()
    chatReset()
    resetAssistant()
    setSidebarOpen(false)
    setSidebarCollapsed(false)
  }, [chatStream, chatReset, resetAssistant])

  /** 空态 / 侧栏「助手」点选：新建绑定该专家的会话（等价于工作模式新任务） */
  const handleStartAssistant = useCallback(
    (id: string) => {
      chatStream.cancel()
      chatReset()
      selectAssistant(id)
      setSidebarOpen(false)
      setSidebarCollapsed(false)
    },
    [chatStream, chatReset, selectAssistant],
  )

  const handleSelect = useCallback(
    (id: string) => {
      if (id === conversationId && !isStreaming) {
        setSidebarOpen(false)
        return
      }
      void chatStream.openConversation(id)
      setSidebarOpen(false)
    },
    [conversationId, isStreaming, chatStream],
  )

  const handleDelete = useCallback(
    async (id: string): Promise<void> => {
      const removed = await removeConversation(id)
      if (removed && id === conversationId) {
        chatReset()
        resetAssistant()
      }
    },
    [removeConversation, conversationId, chatReset, resetAssistant],
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
          isDark={theme.isDark}
          onNew={handleNew}
          onSelect={handleSelect}
          onDelete={handleDelete}
          onCollapse={() => setSidebarCollapsed(true)}
          onSelectAssistant={handleStartAssistant}
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
