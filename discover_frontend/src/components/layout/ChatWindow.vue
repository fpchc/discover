<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import type { ChatMessage } from '@/api/types'
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
}>()

const emit = defineEmits<{
  'toggle-sidebar': []
  retry: []
  /** 空态建议卡片 → 立即发送 */
  suggestion: [text: string]
}>()

const theme = useTheme()

/** 空态建议卡片（面向多智能体平台） */
const suggestions: ReadonlyArray<{ title: string; desc: string; text: string }> = [
  {
    title: '演示一次客户探索',
    desc: '让多智能体团队跑通完整协作流程',
    text: '让多智能体团队演示一次完整的客户探索流程',
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
        <span class="window__model">
          <AppIcon name="sparkle" :size="13" />
          多智能体
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
      <div class="aurora" aria-hidden="true">
        <span class="aurora__blob aurora__blob--1" />
        <span class="aurora__blob aurora__blob--2" />
        <span class="aurora__blob aurora__blob--3" />
      </div>
      <div class="window__hero">
        <h1 class="window__welcome">
          今天，想<span class="window__welcome-accent">探索</span>什么？
        </h1>
        <p class="window__hint">输入问题，或从下面的建议开始，与多智能体团队一起协作</p>
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
.window__model {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-2);
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
}
.window__model :deep(svg) {
  color: var(--brand-2);
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
  .window__model {
    display: none;
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
