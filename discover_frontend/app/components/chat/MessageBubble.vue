<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import type { ChatMessage } from '@/api/types'
import AppIcon from '@/components/common/AppIcon.vue'
import { renderMarkdown } from '@/composables/useMarkdown'
import { FEATURE_THINKING } from '@/config/env'

const props = defineProps<{
  message: ChatMessage
}>()

const emit = defineEmits<{
  retry: []
}>()

/** 助手消息 Markdown 渲染结果（必须经 renderMarkdown 清洗后方可绑定 v-html） */
const rendered = computed<string>(() => renderMarkdown(props.message.content))

const isStreamingEmpty = computed<boolean>(
  () =>
    props.message.role === 'assistant' &&
    props.message.status === 'streaming' &&
    props.message.content === '',
)

const showUsage = computed<boolean>(
  () =>
    props.message.role === 'assistant' &&
    props.message.status === 'done' &&
    props.message.usage !== undefined,
)

/** 思考分区：功能开关开启且消息存在思考状态才渲染（仅助手消息） */
const hasThinking = computed<boolean>(
  () =>
    FEATURE_THINKING &&
    props.message.role === 'assistant' &&
    props.message.thinkingStatus !== undefined,
)

/** 思考进行中：分区强制展开（DeepSeek 式，收尾前只增不减） */
const thinkingActive = computed<boolean>(
  () => hasThinking.value && props.message.thinkingStatus === 'thinking',
)

/** 已结束后的本地折叠开关（用户点击展开 / 收起） */
const thinkingExpanded = ref<boolean>(false)

const thinkingOpen = computed<boolean>(() => thinkingActive.value || thinkingExpanded.value)

function toggleThinking(): void {
  if (thinkingActive.value) return
  thinkingExpanded.value = !thinkingExpanded.value
}

function formatThinkingDuration(): string {
  const ms = props.message.thinkingDurationMs
  if (ms === undefined) return ''
  if (ms < 1000) return '已思考不足 1 秒'
  return `已思考 ${Math.round(ms / 1000)} 秒`
}

async function copyText(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.message.content)
    ElMessage.success('已复制')
  } catch {
    // clipboard 权限被拒时降级提示
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

function formatUsage(): string {
  const usage = props.message.usage
  if (usage === undefined) return ''
  const parts: string[] = []
  if (usage.total_tokens !== undefined) parts.push(`共 ${usage.total_tokens} tokens`)
  if (usage.prompt_tokens !== undefined) parts.push(`提示 ${usage.prompt_tokens}`)
  if (usage.completion_tokens !== undefined) parts.push(`生成 ${usage.completion_tokens}`)
  return parts.join(' · ')
}
</script>

<template>
  <div class="message" :class="`message--${message.role}`">
    <template v-if="message.role === 'assistant'">
      <span class="message__avatar" aria-hidden="true"><AppIcon name="sparkle" :size="14" /></span>
      <div class="message__body">
        <div v-if="hasThinking" class="thinking" :class="{ 'is-active': thinkingActive }">
          <button type="button" class="thinking__header" @click="toggleThinking">
            <span class="thinking__icon"><AppIcon name="sparkle" :size="13" /></span>
            <span class="thinking__title">深度思考</span>
            <span v-if="message.thinkingStatus === 'done'" class="thinking__duration">
              {{ formatThinkingDuration() }}
            </span>
            <span class="thinking__chevron" :class="{ 'is-open': thinkingOpen }">
              <AppIcon name="chevron-down" :size="14" />
            </span>
          </button>
          <div v-show="thinkingOpen" class="thinking__body">{{ message.thinking }}</div>
        </div>

        <div v-if="isStreamingEmpty" class="message__typing" aria-label="正在思考">
          <span class="message__typing-dot" />
          <span class="message__typing-dot" />
          <span class="message__typing-dot" />
        </div>
        <div
          v-else
          class="message__markdown markdown-body"
          :class="{ 'is-streaming': message.status === 'streaming' }"
          v-html="rendered"
        />

        <div v-if="message.status === 'error'" class="message__error">
          <span class="message__error-text">{{ message.errorMessage }}</span>
          <el-button link type="danger" size="small" @click="emit('retry')">重试</el-button>
        </div>
        <div v-if="showUsage" class="message__usage">{{ formatUsage() }}</div>

        <el-button class="message__copy" link size="small" title="复制" @click="copyText">
          <template #icon><AppIcon name="copy" :size="14" /></template>
        </el-button>
      </div>
    </template>
    <template v-else>
      <div class="message__bubble">{{ message.content }}</div>
    </template>
  </div>
</template>

<style scoped>
.message {
  display: flex;
  gap: 12px;
  animation: theme-fade-up 0.3s ease both;
}
.message--assistant {
  align-items: flex-start;
}
.message--user {
  justify-content: flex-end;
}
.message__avatar {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  margin-top: 2px;
  border-radius: 50%;
  background: var(--brand-gradient);
  color: #fff;
  box-shadow: var(--glow-brand);
}
.message__body {
  position: relative;
  flex: 1;
  min-width: 0;
  padding-top: 2px;
}
.message__bubble {
  max-width: 80%;
  padding: 10px 16px;
  border-radius: 16px;
  border-bottom-right-radius: 4px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.9), rgba(139, 92, 246, 0.86));
  color: #fff;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
  line-height: 1.6;
  box-shadow: var(--shadow-card);
}

/* ---- 流式：打字三点 / 正文光标 ---- */
.message__typing {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
}
.message__typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand-2);
  animation: theme-typing-bounce 1.2s ease-in-out infinite;
}
.message__typing-dot:nth-child(2) {
  animation-delay: 0.15s;
}
.message__typing-dot:nth-child(3) {
  animation-delay: 0.3s;
}
.message__markdown {
  line-height: 1.7;
  overflow-wrap: break-word;
}
.message__markdown.is-streaming::after {
  content: '▍';
  margin-left: 1px;
  color: var(--brand-2);
  animation: theme-blink 1s steps(1) infinite;
}

/* ---- 思考分区 ---- */
.thinking {
  margin-bottom: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.06), rgba(139, 92, 246, 0.05));
  overflow: hidden;
}
.thinking__header {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  background: transparent;
  cursor: pointer;
  font: inherit;
  color: var(--text-2);
  text-align: left;
}
.thinking__icon {
  display: inline-flex;
  color: var(--brand-2);
}
.thinking__title {
  font-size: 13px;
  font-weight: 600;
}
.thinking__duration {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-3);
}
.thinking__chevron {
  display: inline-flex;
  color: var(--text-3);
  transition: transform 0.18s ease;
}
.thinking__chevron.is-open {
  transform: rotate(180deg);
}
.thinking.is-active .thinking__header {
  background: linear-gradient(
    100deg,
    transparent 40%,
    rgba(139, 92, 246, 0.12) 50%,
    transparent 60%
  );
  background-size: 220% 100%;
  animation: theme-shimmer 2.4s linear infinite;
}
.thinking__body {
  padding: 8px 12px 10px;
  border-top: 1px solid var(--border-subtle);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---- 错误 / 用量 / 复制 ---- */
.message__error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(244, 63, 94, 0.08);
  color: var(--el-color-danger);
  font-size: 13px;
}
.message__usage {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-3);
}
.message__copy {
  position: absolute;
  top: 0;
  right: 0;
  opacity: 0;
  transition: opacity 0.15s ease;
  color: var(--text-3);
}
.message:hover .message__copy {
  opacity: 1;
}
.message__copy:hover {
  color: var(--text-1);
}

@media (max-width: 767px) {
  .message__bubble {
    max-width: 88%;
  }
}
</style>
