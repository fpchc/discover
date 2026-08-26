<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import ChatWindow from '@/components/layout/ChatWindow.vue'
import { useChatStream } from '@/composables/useChatStream'
import { CHAT_QUERY_MAX } from '@/config/env'
import { useAssistantsStore } from '@/stores/assistants'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'

const chat = useChatStore()
const conversations = useConversationsStore()
const assistants = useAssistantsStore()
const chatStream = useChatStream()

onMounted(() => {
  void chatStream.loadList()
  void chatStream.loadAssistants()
})

/** 移动端侧边栏抽屉开关（<768px 生效） */
const sidebarOpen = ref<boolean>(false)
/** 桌面端侧栏折叠（≥768px 生效） */
const sidebarCollapsed = ref<boolean>(false)

const activeTitle = computed<string>(() => {
  const current = conversations.items.find((item) => item.conversation_id === chat.conversationId)
  return current?.name ?? ''
})

function handleSend(text: string): void {
  void chatStream.send(text)
}

function handleStop(): void {
  chatStream.stop()
}

function handleRetry(): void {
  void chatStream.retry()
}

function handleNew(): void {
  chatStream.cancel()
  chat.reset()
  assistants.resetForNewConversation()
  sidebarOpen.value = false
  sidebarCollapsed.value = false
}

function handleSelect(id: string): void {
  if (id === chat.conversationId && !chat.isStreaming) {
    sidebarOpen.value = false
    return
  }
  void chatStream.openConversation(id)
  sidebarOpen.value = false
}

function handleDelete(id: string): void {
  conversations.remove(id)
  if (id === chat.conversationId) {
    chat.reset()
    assistants.resetForNewConversation()
  }
}

/** 头部侧栏钮：按断点分流——桌面折叠 / 移动抽屉 */
function handleToggleSidebar(): void {
  if (window.matchMedia('(max-width: 767px)').matches) {
    sidebarOpen.value = !sidebarOpen.value
  } else {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }
}

/** 空态建议卡片点击 → 直接发送（由 chatStream 内部拦截流式中重复发送） */
function handleSuggestion(text: string): void {
  handleSend(text)
}
</script>

<template>
  <div class="chat-view">
    <div class="chat-view__bg" aria-hidden="true">
      <span class="chat-view__bg-blob chat-view__bg-blob--1" />
      <span class="chat-view__bg-blob chat-view__bg-blob--2" />
    </div>

    <div
      class="chat-view__sidebar"
      :class="{ 'is-collapsed': sidebarCollapsed, 'is-open': sidebarOpen }"
    >
      <AppSidebar
        :conversations="conversations.items"
        :active-id="chat.conversationId"
        :loading="conversations.loading"
        @new="handleNew"
        @select="handleSelect"
        @delete="handleDelete"
        @collapse="sidebarCollapsed = true"
      />
    </div>
    <div v-if="sidebarOpen" class="chat-view__mask" @click="sidebarOpen = false" />

    <main class="chat-view__main">
      <ChatWindow
        :messages="chat.messages"
        :is-streaming="chat.isStreaming"
        :title="activeTitle"
        :sidebar-collapsed="sidebarCollapsed"
        :usage-summary="chat.usageSummary"
        :history-loading="chat.loadingHistory"
        :assistants="assistants.catalog"
        :selected-assistant-id="assistants.selectedId"
        :assistant-loading="assistants.loading"
        @toggle-sidebar="handleToggleSidebar"
        @retry="handleRetry"
        @suggestion="handleSuggestion"
        @assistant-change="assistants.select"
      />
      <div class="chat-view__input">
        <ChatInput
          :disabled="chat.isStreaming"
          :max-length="CHAT_QUERY_MAX"
          @send="handleSend"
          @stop="handleStop"
        />
        <p class="chat-view__disclaimer">内容由 AI 生成，请仔细甄别</p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.chat-view {
  position: relative;
  display: flex;
  height: 100%;
  overflow: hidden;
}

/* 页面级淡光晕（整体氛围；欢迎区另有更强的 aurora） */
.chat-view__bg {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}
.chat-view__bg-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(140px);
  opacity: 0.5;
  animation: theme-aurora-drift 30s ease-in-out infinite alternate;
}
.chat-view__bg-blob--1 {
  top: -30%;
  left: -10%;
  width: 640px;
  height: 640px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.35), transparent 65%);
}
.chat-view__bg-blob--2 {
  bottom: -32%;
  right: -8%;
  width: 560px;
  height: 560px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.26), transparent 65%);
  animation-delay: -12s;
}

.chat-view__sidebar {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
  width: 260px;
  overflow: hidden;
  transition: width 0.25s ease;
}
.chat-view__sidebar.is-collapsed {
  width: 0;
  border-right: none;
}
.chat-view__main {
  position: relative;
  z-index: 1;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chat-view__input {
  /* 输入区为固定工具栏，永不参与 flex 收缩 */
  flex-shrink: 0;
  padding: 4px 24px 14px;
  max-width: 860px;
  width: 100%;
  margin: 0 auto;
}
.chat-view__disclaimer {
  margin: 10px 0 0;
  text-align: center;
  font-size: 12px;
  color: var(--text-3);
}
.chat-view__mask {
  display: none;
}

@media (max-width: 767px) {
  .chat-view__sidebar,
  .chat-view__sidebar.is-collapsed {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 100;
    width: 260px;
    transform: translateX(-100%);
    transition: transform 0.22s ease;
  }
  .chat-view__sidebar.is-open {
    transform: translateX(0);
    box-shadow: var(--shadow-float);
  }
  .chat-view__mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 99;
    background: rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(2px);
  }
  .chat-view__input {
    padding: 2px 12px 10px;
  }
}
</style>
