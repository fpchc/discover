<script setup lang="ts">
import { computed, ref } from 'vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import ChatWindow from '@/components/layout/ChatWindow.vue'
import { useChatStream } from '@/composables/useChatStream'
import { CHAT_QUERY_MAX } from '@/config/env'
import { useChatStore } from '@/stores/chat'
import { useConversationsStore } from '@/stores/conversations'

const chat = useChatStore()
const conversations = useConversationsStore()
const chatStream = useChatStream()

/** 移动端侧边栏抽屉开关（<768px 生效） */
const sidebarOpen = ref<boolean>(false)

const activeTitle = computed<string>(() => {
  const current = conversations.items.find((item) => item.conversation_id === chat.conversationId)
  return current?.title ?? ''
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
  sidebarOpen.value = false
}

function handleSelect(id: string): void {
  if (id === chat.conversationId && !chat.isStreaming) {
    sidebarOpen.value = false
    return
  }
  chatStream.cancel()
  chat.loadConversation(id)
  sidebarOpen.value = false
}

function handleDelete(id: string): void {
  chat.clearSnapshot(id)
  conversations.remove(id)
  if (id === chat.conversationId) {
    chat.reset()
  }
}
</script>

<template>
  <div class="chat-view">
    <div class="chat-view__sidebar" :class="{ 'is-open': sidebarOpen }">
      <AppSidebar
        :conversations="conversations.items"
        :active-id="chat.conversationId"
        @new="handleNew"
        @select="handleSelect"
        @delete="handleDelete"
      />
    </div>
    <div v-if="sidebarOpen" class="chat-view__mask" @click="sidebarOpen = false" />
    <main class="chat-view__main">
      <ChatWindow
        :messages="chat.messages"
        :is-streaming="chat.isStreaming"
        :title="activeTitle"
        @toggle-sidebar="sidebarOpen = !sidebarOpen"
        @retry="handleRetry"
      />
      <div class="chat-view__input">
        <ChatInput
          :disabled="chat.isStreaming"
          :max-length="CHAT_QUERY_MAX"
          @send="handleSend"
          @stop="handleStop"
        />
      </div>
    </main>
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  height: 100%;
  overflow: hidden;
}
.chat-view__sidebar {
  flex-shrink: 0;
}
.chat-view__main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chat-view__input {
  padding: 12px 24px 20px;
  max-width: 860px;
  width: 100%;
  margin: 0 auto;
}
.chat-view__mask {
  display: none;
}

@media (max-width: 767px) {
  .chat-view__sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 100;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
  }
  .chat-view__sidebar.is-open {
    transform: translateX(0);
    box-shadow: var(--el-box-shadow-dark);
  }
  .chat-view__mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 99;
    background: rgba(0, 0, 0, 0.3);
  }
  .chat-view__input {
    padding: 8px 12px 14px;
  }
}
</style>
