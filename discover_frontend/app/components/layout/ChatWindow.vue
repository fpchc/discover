<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { AssistantRecord, ChatMessage, ConversationUsage } from '@/api/types'
import AssistantPicker from '@/components/chat/AssistantPicker.vue'
import MessageBubble from '@/components/chat/MessageBubble.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { useTheme } from '@/composables/useTheme'

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
  /** 助手目录（API.md §6.1；供头部选择器渲染选项） */
  assistants: AssistantRecord[]
  /** 当前选择的助手 id（专家 id / 'generic'） */
  selectedAssistantId: string
  /** 助手目录加载中 */
  assistantLoading: boolean
}>()

const emit = defineEmits<{
  'toggle-sidebar': []
  retry: []
  /** 空态建议卡片 → 立即发送 */
  suggestion: [text: string]
  /** 助手选择器变更 → 下一次 /chat-messages 生效 */
  'assistant-change': [id: string]
}>()

const theme = useTheme()

/** 头部轻量用量角标：`X 回合 · Y tokens`；无数据不显示 */
const usageLabel = computed<string>(() => {
  const usage = props.usageSummary
  if (usage === null) return ''
  return `${usage.message_count} 回合 · ${usage.total_tokens.toLocaleString()} tokens`
})

/** 空态建议卡片（显式选择助手后即用，不依赖 LLM 自动路由） */
const suggestions: ReadonlyArray<{ title: string; desc: string; text: string }> = [
  {
    title: '演示一次客户探索',
    desc: '让客户发现助手跑通完整探索流程',
    text: '演示一次完整的客户探索流程',
  },
  {
    title: '拆解并规划需求',
    desc: '把一份业务需求拆成可执行计划',
    text: '帮我拆解并规划一份业务需求',
  },
  {
    title: '对比方案给出建议',
    desc: '多角度评估，输出权衡后的结论',
    text: '对比两种方案并给出建议',
  },
  {
    title: '提炼核心要点',
    desc: '快速总结内容的关键信息',
    text: '把这段内容提炼成要点',
  },
]

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
        <AssistantPicker
          class="window__picker"
          :catalog="assistants"
          :selected-id="selectedAssistantId"
          :loading="assistantLoading"
          :disabled="isStreaming"
          @change="emit('assistant-change', $event)"
        />
        <span v-if="usageLabel !== ''" class="window__usage" :title="usageLabel">
          {{ usageLabel }}
        </span>
        <el-button
          class="window__theme"
          link
          circle
          size="small"
          :title="theme.isDark ? '切换到浅色' : '切换到深色'"
          @click="theme.toggle"
        >
          <AppIcon :name="theme.isDark ? 'sun' : 'moon'" :size="17" />
        </el-button>
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
          <p class="window__hint">先选一位助手，再输入问题开始探索</p>
          <div class="window__suggestions">
            <button
              v-for="suggestion in suggestions"
              :key="suggestion.title"
              type="button"
              class="window__suggestion"
              @click="emit('suggestion', suggestion.text)"
            >
              <span class="window__suggestion-icon"><AppIcon name="sparkle" :size="15" /></span>
              <span class="window__suggestion-text">
                <span class="window__suggestion-title">{{ suggestion.title }}</span>
                <span class="window__suggestion-desc">{{ suggestion.desc }}</span>
              </span>
            </button>
          </div>
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
.window__picker {
  flex-shrink: 0;
}
.window__usage {
  font-size: 12px;
  color: var(--text-3);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.window__theme {
  color: var(--text-2);
}
.window__theme:hover {
  color: var(--text-1);
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
  margin: 12px 0 28px;
  font-size: 14px;
  color: var(--text-2);
}
.window__suggestions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.window__suggestion {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: var(--surface-1);
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: var(--text-1);
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}
.window__suggestion:hover {
  transform: translateY(-2px);
  border-color: var(--brand-2);
  box-shadow: var(--shadow-card);
}
.window__suggestion-icon {
  display: inline-flex;
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--brand-2);
  transition: transform 0.18s ease;
}
.window__suggestion:hover .window__suggestion-icon {
  transform: scale(1.15) rotate(-8deg);
}
.window__suggestion-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.window__suggestion-title {
  font-size: 13px;
  font-weight: 600;
}
.window__suggestion-desc {
  font-size: 12px;
  color: var(--text-3);
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
  .window__suggestions {
    grid-template-columns: 1fr;
  }
}
</style>
