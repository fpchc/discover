<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import type { ChatMessage } from '@/api/types'
import MessageBubble from '@/components/chat/MessageBubble.vue'

const props = defineProps<{
  messages: ChatMessage[]
  isStreaming: boolean
  /** 当前会话标题（空串 = 新对话） */
  title: string
}>()

const emit = defineEmits<{
  'toggle-sidebar': []
  retry: []
}>()

const scrollRef = ref<HTMLElement | null>(null)

function scrollToBottom(): void {
  const el = scrollRef.value
  if (el === null) return
  el.scrollTop = el.scrollHeight
}

watch(
  () => props.messages,
  () => {
    void nextTick(scrollToBottom)
  },
  { deep: true },
)

onMounted(scrollToBottom)
</script>

<template>
  <section class="chat-window">
    <header class="chat-window__header">
      <el-button class="chat-window__menu" link @click="emit('toggle-sidebar')">☰</el-button>
      <span class="chat-window__title">{{ title || '新对话' }}</span>
    </header>
    <div ref="scrollRef" class="chat-window__scroll">
      <div v-if="messages.length === 0" class="chat-window__empty">
        <h1 class="chat-window__welcome">今天想探索什么？</h1>
        <p class="chat-window__hint">输入问题，开始与多智能体团队对话</p>
      </div>
      <div v-else class="chat-window__messages">
        <MessageBubble
          v-for="message in messages"
          :key="message.id"
          :message="message"
          @retry="emit('retry')"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat-window {
  display: flex;
  flex-direction: column;
  flex: 1;
  height: 100%;
  min-width: 0;
}
.chat-window__header {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 52px;
  padding: 0 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.chat-window__menu {
  display: none;
}
.chat-window__title {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-window__scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}
.chat-window__messages {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 860px;
  margin: 0 auto;
}
.chat-window__empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
}
.chat-window__welcome {
  margin: 0;
  font-size: 28px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.chat-window__hint {
  margin: 0;
  color: var(--el-text-color-secondary);
}

@media (max-width: 767px) {
  .chat-window__menu {
    display: inline-flex;
  }
  .chat-window__scroll {
    padding: 16px;
  }
}
</style>
