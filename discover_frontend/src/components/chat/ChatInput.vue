<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import AppIcon from '@/components/common/AppIcon.vue'

const props = defineProps<{
  /** 发送中：隐藏发送、显示「停止」 */
  disabled: boolean
  /** query 长度上限（对齐后端） */
  maxLength: number
}>()

const emit = defineEmits<{
  send: [text: string]
  stop: []
}>()

const text = ref<string>('')
const composing = ref<boolean>(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const canSend = computed<boolean>(
  () => !props.disabled && text.value.trim() !== '' && text.value.length <= props.maxLength,
)

function resize(): void {
  const el = textareaRef.value
  if (el === null) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

function submit(): void {
  if (props.disabled || composing.value) return
  const trimmed = text.value.trim()
  if (trimmed === '') return
  if (trimmed.length > props.maxLength) {
    ElMessage.warning(`消息长度不能超过 ${props.maxLength} 字`)
    return
  }
  emit('send', trimmed)
  text.value = ''
  requestAnimationFrame(resize)
}

function handleKeydown(event: KeyboardEvent): void {
  // Enter 发送、Shift+Enter 换行（合成输入中不触发）
  if (event.key === 'Enter' && !event.shiftKey && !composing.value) {
    event.preventDefault()
    submit()
  }
}
</script>

<template>
  <div class="input" :class="{ 'is-disabled': disabled }">
    <textarea
      ref="textareaRef"
      v-model="text"
      class="input__textarea"
      :maxlength="maxLength"
      :placeholder="disabled ? '正在生成回复…' : '发送消息，和你的智能体团队对话'"
      rows="1"
      @input="resize"
      @keydown="handleKeydown"
      @compositionstart="composing = true"
      @compositionend="composing = false"
    />
    <div class="input__footer">
      <span class="input__hint">Enter 发送 · Shift+Enter 换行</span>
      <div class="input__side">
        <span class="input__counter">{{ text.length }}/{{ maxLength }}</span>
        <el-button
          v-if="disabled"
          class="input__stop"
          circle
          title="停止生成"
          @click="emit('stop')"
        >
          <template #icon><AppIcon name="square" :size="13" /></template>
        </el-button>
        <el-button
          v-else
          class="input__send"
          circle
          :disabled="!canSend"
          title="发送"
          @click="submit"
        >
          <template #icon><AppIcon name="arrow-up" :size="16" /></template>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.input {
  border: 1px solid var(--border-strong);
  border-radius: 20px;
  padding: 12px 16px 10px;
  background: var(--surface-1);
  box-shadow: var(--shadow-composer);
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    background-color 0.2s ease;
}
.input:focus-within {
  border-color: var(--brand-2);
  box-shadow: var(--glow-primary), var(--shadow-composer);
}
.input.is-disabled {
  opacity: 0.85;
}
.input__textarea {
  display: block;
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  max-height: 200px;
  font: inherit;
  font-size: 14px;
  line-height: 1.6;
  background: transparent;
  color: var(--text-1);
}
.input__textarea::placeholder {
  color: var(--text-3);
}
.input__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
.input__hint {
  font-size: 12px;
  color: var(--text-3);
  user-select: none;
}
.input__side {
  display: flex;
  align-items: center;
  gap: 10px;
}
.input__counter {
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.input__send.el-button {
  width: 36px;
  height: 36px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: var(--brand-gradient);
  color: #fff;
  box-shadow: var(--glow-brand);
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease,
    background-color 0.15s ease;
}
.input__send.el-button:hover:not(.is-disabled) {
  transform: scale(1.06);
  box-shadow: 0 8px 26px rgba(139, 92, 246, 0.5);
}
.input__send.el-button.is-disabled {
  background: var(--surface-hover);
  color: var(--text-3);
  box-shadow: none;
}
.input__stop.el-button {
  width: 36px;
  height: 36px;
  padding: 0;
  border-radius: 50%;
  border: 1px solid var(--border-subtle);
  background: var(--surface-2);
  color: var(--text-1);
  transition: background-color 0.15s ease;
}
.input__stop.el-button:hover {
  background: var(--surface-hover);
}

@media (max-width: 767px) {
  .input__hint {
    display: none;
  }
  .input {
    border-radius: 16px;
    padding: 10px 14px 8px;
  }
}
</style>
