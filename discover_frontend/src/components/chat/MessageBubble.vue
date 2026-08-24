<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed } from 'vue'
import type { ChatMessage } from '@/api/types'
import { renderMarkdown } from '@/composables/useMarkdown'

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
  <div class="message-bubble" :class="`message-bubble--${message.role}`">
    <div class="message-bubble__content">
      <div v-if="message.role === 'user'" class="message-bubble__text">
        {{ message.content }}
      </div>
      <template v-else>
        <div v-if="isStreamingEmpty" class="message-bubble__placeholder">正在思考…</div>
        <div
          v-else
          class="message-bubble__markdown"
          :class="{ 'is-streaming': message.status === 'streaming' }"
          v-html="rendered"
        />
        <div v-if="message.status === 'error'" class="message-bubble__error">
          <span class="message-bubble__error-text">{{ message.errorMessage }}</span>
          <el-button link type="danger" size="small" @click="emit('retry')">重试</el-button>
        </div>
        <div v-if="showUsage" class="message-bubble__usage">{{ formatUsage() }}</div>
      </template>
      <el-button class="message-bubble__copy" link size="small" @click="copyText">复制</el-button>
    </div>
  </div>
</template>

<style scoped>
.message-bubble {
  display: flex;
  padding: 6px 0;
}
.message-bubble--user {
  justify-content: flex-end;
}
.message-bubble__content {
  position: relative;
  max-width: 80%;
  padding: 10px 14px;
  border-radius: 12px;
  background: var(--el-fill-color-light);
  white-space: pre-wrap;
  word-break: break-word;
}
.message-bubble--user .message-bubble__content {
  background: var(--el-color-primary-light-8);
}
.message-bubble__text {
  line-height: 1.6;
}
.message-bubble__markdown {
  line-height: 1.6;
  overflow-wrap: break-word;
  white-space: normal;
}
.message-bubble__markdown.is-streaming::after {
  content: '▍';
  margin-left: 1px;
  color: var(--el-color-primary);
  animation: message-bubble-blink 1s steps(1) infinite;
}
@keyframes message-bubble-blink {
  50% {
    opacity: 0;
  }
}
.message-bubble__placeholder {
  color: var(--el-text-color-placeholder);
  font-style: italic;
}
.message-bubble__error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--el-color-danger-light-5);
  color: var(--el-color-danger);
  font-size: 13px;
}
.message-bubble__usage {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--el-border-color-lighter);
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.message-bubble__copy {
  position: absolute;
  top: 4px;
  right: 6px;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.message-bubble__content:hover .message-bubble__copy {
  opacity: 1;
}
</style>
