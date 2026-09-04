import { useEffect, useMemo, useRef } from 'react'
import { toast } from 'sonner'
import {
  CHAT_QUERY_MAX,
  CONVERSATION_TITLE_MAX,
  FEATURE_BLOCKING_FALLBACK,
  SSE_TIMEOUT_MS,
} from '@/env'
import {
  fetchAssistants,
  fetchConversations,
  fetchMessages,
  sendChatMessage,
  sendChatMessageBlocking,
  stopChatMessage,
} from '@/lib/api'
import {
  type AppError,
  HttpError,
  mapHttpError,
  readResponseError,
  TIMEOUT_ERROR,
} from '@/lib/errors'
import { mapMessageRecords } from '@/lib/history'
import { consumeChatStream, readConversationId, resolveTurnEnd } from '@/lib/stream'
import { useAssistantsStore } from '@/stores/assistants'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'
import type { ConversationRecord } from '@/types'

/**
 * 对话发送编排（CLAUDE.md 第 5 节 + performance.md §4）。职责：
 * - 会话首次创建 / 续聊复用（X-Conversation-Id 头优先，帧内 id 兜底）；
 * - 流式 / 阻塞（兜底）两种 response_mode；
 * - 停止走服务端显式 stop（POST /chat-messages/{id}/stop，流关闭即停止生效），失败退回本地
 *   AbortController 取消；SSE_TIMEOUT_MS 整体超时；
 * - turn 作废机制：切换 / 新建会话后，旧流残留帧与回调不再落库（防幽灵增量）；
 * - 组件卸载时 abort() 清理（performance.md §4，杜绝后台幽灵请求）。
 * 本层只驱动 store（单一事实源），不做 UI 渲染。
 */
export interface ChatStreamApi {
  send: (query: string) => Promise<void>
  retry: () => Promise<void>
  stop: () => void
  cancel: () => void
  loadList: () => Promise<void>
  loadAssistants: () => Promise<void>
  reconcileList: () => Promise<void>
  openConversation: (conversationId: string) => Promise<void>
}

export function useChatStream(): ChatStreamApi {
  // 可变编排状态（不触发重渲；hook 生命周期与 App 挂载一致）
  const ctx = useRef<{
    controller: AbortController | null
    userCancelled: boolean
    lastQuery: string
    turnSeq: number
  }>({ controller: null, userCancelled: false, lastQuery: '', turnSeq: 0 })

  const api = useMemo<ChatStreamApi>(() => {
    const chat = (): ReturnType<typeof useChatStore.getState> => useChatStore.getState()
    const conversations = (): ReturnType<typeof useConversationsStore.getState> =>
      useConversationsStore.getState()
    const assistants = (): ReturnType<typeof useAssistantsStore.getState> =>
      useAssistantsStore.getState()

    function isAbortError(error: unknown): boolean {
      return error instanceof DOMException && error.name === 'AbortError'
    }

    function isCurrent(turn: number): boolean {
      return turn === ctx.current.turnSeq
    }

    /** 新会话乐观入列（name 取首条 query 截断）；回合结束后由 reconcileList 校准后端权威值 */
    function registerConversation(conversationId: string): void {
      const state = chat()
      const isNew = state.conversationId === ''
      state.setConversationId(conversationId)
      if (isNew) {
        const now = new Date().toISOString()
        const optimistic: ConversationRecord = {
          conversation_id: conversationId,
          agent_id: null,
          model_provider: null,
          model_id: null,
          name: ctx.current.lastQuery.slice(0, CONVERSATION_TITLE_MAX),
          summary: null,
          status: 'active',
          dialogue_count: 1,
          created_at: now,
          updated_at: now,
        }
        conversations().add(optimistic)
      } else {
        conversations().touch(conversationId)
      }
    }

    /**
     * 加载会话列表。已有缓存 / 已加载列表时不再置骨架态（刷新 / 重回对话页直接显示旧列表，
     * 后端就绪后 replaceAll 全量校准）；无数据首次加载仍显示骨架占位。
     */
    async function loadList(): Promise<void> {
      const hasItems = conversations().items.length > 0
      if (!hasItems) conversations().setLoading(true)
      try {
        conversations().replaceAll(await fetchConversations())
      } catch {
        // 拉取失败：保留缓存 / 现状，不阻断对话
      } finally {
        conversations().setLoading(false)
      }
    }

    /** 首次加载助手目录（聊天页入口）；失败静默，选择器降级为通用对话（空 agent_id 兜底） */
    async function loadAssistants(): Promise<void> {
      assistants().setLoading(true)
      try {
        assistants().setCatalog(await fetchAssistants())
      } catch {
        // 目录拉取失败：保持空目录，不阻断对话
      } finally {
        assistants().setLoading(false)
      }
    }

    /** 静默校准：回合结束后用后端权威数据覆盖乐观入列，不触发侧栏加载态 */
    async function reconcileList(): Promise<void> {
      try {
        conversations().replaceAll(await fetchConversations())
      } catch {
        // 校准失败保留乐观值
      }
    }

    /** 切换会话：作废旧流 → 拉取后端历史消息（必取）→ 写入 store */
    async function openConversation(conversationId: string): Promise<void> {
      cancel()
      chat().setLoadingHistory(true)
      chat().setConversationId(conversationId)
      chat().setMessages([])
      // 选择器对齐会话已绑定助手（会话列表来自后端 GET /conversations；未绑定 → 通用）
      const record = conversations().items.find((item) => item.conversation_id === conversationId)
      assistants().syncFromConversation(record?.agent_id ?? null)
      try {
        const records = await fetchMessages(conversationId)
        chat().setMessages(mapMessageRecords(records))
      } catch (error) {
        toast.error(mapHttpError(error).message)
      } finally {
        chat().setLoadingHistory(false)
      }
    }

    async function runTurn(query: string, mode: 'streaming' | 'blocking'): Promise<void> {
      const turn = ++ctx.current.turnSeq
      ctx.current.userCancelled = false
      const localController = new AbortController()
      ctx.current.controller = localController
      const timeoutId = window.setTimeout(() => localController.abort(), SSE_TIMEOUT_MS)
      const current = (): boolean => isCurrent(turn)

      try {
        if (mode === 'blocking') {
          const data = await sendChatMessageBlocking({
            query,
            conversationId: chat().conversationId,
            agentId: assistants().selectedId,
            signal: localController.signal,
          })
          if (!current()) return
          registerConversation(data.conversation_id)
          chat().completeAssistant()
          assistants().syncFromAssistant(data.metadata.assistant)
          return
        }

        const response = await sendChatMessage({
          query,
          conversationId: chat().conversationId,
          agentId: assistants().selectedId,
          signal: localController.signal,
        })
        if (!response.ok) {
          throw await readResponseError(response)
        }
        const headerId = readConversationId(response)
        if (headerId !== '') {
          if (!current()) return
          registerConversation(headerId)
        }
        await consumeChatStream(response, {
          onDelta: (delta) => {
            if (current()) chat().appendDelta(delta)
          },
          onThinkingStart: () => {
            if (current()) chat().startThinking()
          },
          onThinkingDelta: (delta) => {
            if (current()) chat().appendThinking(delta)
          },
          onThinkingEnd: (durationMs) => {
            if (current()) chat().endThinking(durationMs)
          },
          onEnd: (metadata, conversationId) => {
            if (!current()) return
            if (conversationId !== '') registerConversation(conversationId)
            if (resolveTurnEnd(metadata) === 'abort') {
              // 用户 stop → 服务端 RunCancelled 收尾：与本地 abort 兜底同语义
              // （空内容移除 / 非空保留并标记完成，不留空气泡）
              chat().abortTurn()
            } else {
              chat().completeAssistant()
            }
            assistants().syncFromAssistant(metadata.assistant)
          },
          onError: (error: AppError) => {
            if (!current()) return
            if (ctx.current.userCancelled) {
              // 用户主动停止：POST stop 后服务端关闭流（STREAM_INTERRUPTED）/ 本地 abort
              // 兜底 → 保留已收内容并标记完成，不视为错误
              chat().abortTurn()
            } else if (error.status === 401) {
              // SSE 帧级 401：令牌失效 → 全局会话过期（回到登录页）
              useAuthStore.getState().expire()
            } else {
              chat().failAssistant(error.message)
            }
          },
        })
      } catch (error) {
        if (!current()) return
        if (ctx.current.userCancelled) {
          chat().abortTurn()
        } else if (isAbortError(error)) {
          chat().failAssistant(TIMEOUT_ERROR.message)
        } else if (error instanceof HttpError) {
          if (error.appError.status === 401) {
            // 响应级 401（如对话请求未经认证）：全局会话过期 → 回到登录页
            useAuthStore.getState().expire()
          } else {
            chat().failAssistant(error.appError.message)
          }
        } else {
          chat().failAssistant(mapHttpError(error).message)
        }
      } finally {
        if (current()) window.clearTimeout(timeoutId)
      }
    }

    async function send(query: string): Promise<void> {
      if (chat().isStreaming) return
      const trimmed = query.trim()
      if (trimmed === '' || trimmed.length > CHAT_QUERY_MAX) return
      ctx.current.lastQuery = trimmed
      chat().beginTurn(trimmed)
      await runTurn(trimmed, 'streaming')
      // 回合结束（message_end / 失败）后用后端权威列表校准乐观入列与 touch
      void reconcileList()
    }

    /** 失败重试：优先走 blocking 兜底（受功能开关控制），不再追加用户消息 */
    async function retry(): Promise<void> {
      if (chat().isStreaming || ctx.current.lastQuery === '') return
      chat().beginRetryTurn()
      await runTurn(ctx.current.lastQuery, FEATURE_BLOCKING_FALLBACK ? 'blocking' : 'streaming')
    }

    /**
     * 停止生成：保留已收内容，复位流式状态。
     * 优先走服务端显式停止（POST /chat-messages/{id}/stop）：返回 stopping 后不中断本地流，
     * 等服务端取消回合 → SSE 流关闭即停止生效（无轮询，契约见后端交付）；请求失败 / 后端
     * 无进行中回合（idle）时退回本地 abort 兜底，保证任何情况下停止都有效。
     * 新会话首轮在响应头回传 ID 前无服务端对象可停，直接本地 abort。
     */
    function stop(): void {
      if (!chat().isStreaming || ctx.current.userCancelled) return
      ctx.current.userCancelled = true
      const conversationId = chat().conversationId
      if (conversationId === '') {
        ctx.current.controller?.abort()
        return
      }
      void (async () => {
        try {
          const result = await stopChatMessage(conversationId)
          if (result.status !== 'stopping') {
            ctx.current.controller?.abort()
          }
        } catch {
          ctx.current.controller?.abort()
        }
      })()
    }

    /** 切换 / 新建会话：作废当前轮 token，旧流残留帧不再落库 */
    function cancel(): void {
      ctx.current.userCancelled = true
      ctx.current.turnSeq += 1
      ctx.current.controller?.abort()
      ctx.current.controller = null
    }

    return { send, retry, stop, cancel, loadList, loadAssistants, reconcileList, openConversation }
  }, [])

  useEffect(() => {
    // 卸载清理（performance.md §4）：abort 正在进行的流，杜绝后台幽灵请求写脏状态
    return () => {
      ctx.current.userCancelled = true
      ctx.current.turnSeq += 1
      ctx.current.controller?.abort()
    }
  }, [])

  return api
}
