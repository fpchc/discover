<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { ChatMessage, ConversationUsage } from '@/api/types'
import MessageBubble from '@/components/chat/MessageBubble.vue'
import AppIcon from '@/components/common/AppIcon.vue'

const props = defineProps<{
  messages: ChatMessage[]
  isStreaming: boolean
  /** 当前会话标题（空串 = 新对话） */
  title: string
  /** 桌面侧栏是否已折叠（折叠时头部显示展开钮） */
  sidebarCollapsed: boolean
  /** 当前会话用量汇总（GET /conversations/{id}/usage；新对话为 null） */
  usageSummary: ConversationUsage | null
  /** 历史消息加载中（切换会话时） */
  historyLoading: boolean
}>()

const emit = defineEmits<{
  'toggle-sidebar': []
  retry: []
}>()

/** 头部轻量用量角标：`X 回合 · Y tokens`；无数据不显示 */
const usageLabel = computed<string>(() => {
  const usage = props.usageSummary
  if (usage === null) return ''
  return `${usage.message_count} 回合 · ${usage.total_tokens.toLocaleString()} tokens`
})

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
  <section class="window">
    <header class="window__header">
      <el-button
        class="window__btn window__btn--mobile"
        link
        circle
        size="small"
        title="打开侧栏"
        @click="emit('toggle-sidebar')"
      >
        <AppIcon name="menu" :size="18" />
      </el-button>
      <el-button
        v-if="sidebarCollapsed"
        class="window__btn window__btn--desktop"
        link
        circle
        size="small"
        title="展开侧栏"
        @click="emit('toggle-sidebar')"
      >
        <AppIcon name="panel-left" :size="18" />
      </el-button>

      <span class="window__title">{{ title || '新对话' }}</span>

      <div class="window__actions">
        <span v-if="usageLabel !== ''" class="window__usage" :title="usageLabel">
          {{ usageLabel }}
        </span>
      </div>
    </header>

    <div v-if="messages.length === 0" class="window__empty">
      <div v-if="historyLoading" class="window__loading">
        <el-icon class="is-loading"><AppIcon name="sparkle" :size="18" /></el-icon>
        <span>正在加载会话…</span>
      </div>
      <template v-else>
        <div class="aurora" aria-hidden="true">
          <span class="aurora__blob aurora__blob--1" />
          <span class="aurora__blob aurora__blob--2" />
          <span class="aurora__blob aurora__blob--3" />
        </div>
        <div class="window__hero">
          <h1 class="window__welcome">
            今天，想<span class="window__welcome-accent">探索</span>什么？
          </h1>
          <p class="window__hint">在下方输入框选择助手，开始你的探索</p>
        </div>
      </template>
    </div>

    <div v-else ref="scrollRef" class="window__scroll">
      <div class="window__messages">
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
.window {
  display: flex;
  flex-direction: column;
  flex: 1;
  height: 100%;
  min-width: 0;
  /* 允许在 flex 列布局中收缩：缺省 min-height:auto 会让 .window 按内容撑高，
     把下方输入框挤出可视区（进入历史会话后复现），须显式归零 */
  min-height: 0;
}
.window__header {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 56px;
  padding: 0 16px;
  flex-shrink: 0;
}
.window__btn {
  color: var(--text-2);
}
.window__btn:hover {
  color: var(--text-1);
}
.window__btn--mobile {
  display: none;
}
.window__btn--desktop {
  display: none;
}
@media (min-width: 768px) {
  .window__btn--desktop {
    display: inline-flex;
  }
}
.window__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 600;
  text-align: center;
}
.window__actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.window__usage {
  font-size: 12px;
  color: var(--text-3);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* ---- 空态：光晕 + 欢迎区 ---- */
.window__empty {
  position: relative;
  flex: 1;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}
.window__loading {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-3);
}
.window__loading :deep(svg) {
  color: var(--brand-2);
}
.aurora {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}
.aurora__blob {
  position: absolute;
  width: 480px;
  height: 480px;
  border-radius: 50%;
  filter: blur(var(--aurora-blur));
  opacity: var(--aurora-opacity);
  animation: theme-aurora-drift 22s ease-in-out infinite alternate;
}
.aurora__blob--1 {
  top: -12%;
  left: -10%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.55), transparent 65%);
}
.aurora__blob--2 {
  top: 18%;
  right: -14%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.42), transparent 65%);
  animation-delay: -7s;
}
.aurora__blob--3 {
  bottom: -18%;
  left: 28%;
  background: radial-gradient(circle, rgba(167, 139, 250, 0.32), transparent 65%);
  animation-delay: -14s;
}
.window__hero {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 640px;
  padding: 24px;
  text-align: center;
  animation: theme-fade-up 0.5s ease both;
}
.window__welcome {
  margin: 0;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: 0.01em;
  color: var(--text-1);
}
.window__welcome-accent {
  background: var(--brand-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.window__hint {
  margin: 12px 0 0;
  font-size: 14px;
  color: var(--text-2);
}

/* ---- 消息区 ---- */
.window__scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px 32px;
}
.window__messages {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 860px;
  margin: 0 auto;
}

@media (max-width: 767px) {
  .window__btn--mobile {
    display: inline-flex;
  }
  .window__welcome {
    font-size: 24px;
  }
  .window__scroll {
    padding: 12px 16px 24px;
  }
}
</style>
