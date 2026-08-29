import { create } from 'zustand'

/**
 * 应用视图状态（CLAUDE.md §3：跨组件共享状态一律走 Zustand；§11：仅 UI 状态走 localStorage，`disf_` 前缀）。
 * 主区视图（对话 / 用户中心）+ 用户中心菜单（个人中心 / 用量）+ 当前打开会话 ID 持久化到
 * localStorage，刷新后停留在当前页面 / 对话（单一事实源读自 localStorage，与 stores/theme.ts 同模式）。
 * 只存 UI 导航状态与「当前会话」指针，不存会话 / 消息正文数据（后端为唯一事实源）。
 */
export type AppView = 'chat' | 'center'
export type CenterTab = 'profile' | 'usage'

const VIEW_KEY = 'disf_view'
const TAB_KEY = 'disf_center_tab'
const CONVERSATION_KEY = 'disf_conversation_id'

function readRaw(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    // 隐私模式：不可读，走默认值
    return null
  }
}

function writeRaw(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // 隐私模式：仅内存态生效
  }
}

export interface ViewState {
  view: AppView
  centerTab: CenterTab
  /** 持久化的当前会话 ID（刷新后恢复打开的对话；chat store 仍为运行时事实源，本字段仅镜像） */
  savedConversationId: string
  setView: (view: AppView) => void
  setCenterTab: (tab: CenterTab) => void
  setSavedConversationId: (conversationId: string) => void
}

function readInitialView(): AppView {
  return readRaw(VIEW_KEY) === 'center' ? 'center' : 'chat'
}

function readInitialTab(): CenterTab {
  return readRaw(TAB_KEY) === 'usage' ? 'usage' : 'profile'
}

function readInitialConversation(): string {
  return readRaw(CONVERSATION_KEY) ?? ''
}

export const useViewStore = create<ViewState>((set) => ({
  view: readInitialView(),
  centerTab: readInitialTab(),
  savedConversationId: readInitialConversation(),

  setView: (view) => {
    set({ view })
    writeRaw(VIEW_KEY, view)
  },

  setCenterTab: (centerTab) => {
    set({ centerTab })
    writeRaw(TAB_KEY, centerTab)
  },

  setSavedConversationId: (conversationId) => {
    set({ savedConversationId: conversationId })
    writeRaw(CONVERSATION_KEY, conversationId)
  },
}))
