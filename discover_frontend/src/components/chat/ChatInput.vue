<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'

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
  <div class="chat-input">
    <textarea
      ref="textareaRef"
      v-model="text"
      class="chat-input__textarea"
      :maxlength="maxLength"
      :placeholder="disabled ? '正在生成回复…' : '发送消息（Enter 发送，Shift+Enter 换行）'"
      rows="1"
      @input="resize"
      @keydown="handleKeydown"
      @compositionstart="composing = true"
      @compositionend="composing = false"
    />
    <div class="chat-input__footer">
      <span class="chat-input__counter">{{ text.length }}/{{ maxLength }}</span>
      <el-button v-if="disabled" class="chat-input__stop" type="danger" plain size="small" @click="emit('stop')">
        停止
      </el-button>
      <el-button v-else class="chat-input__send" type="primary" size="small" :disabled="!canSend" @click="submit">
        发送
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.chat-input {
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 10px 12px;
  background: var(--el-bg-color);
  box-shadow: var(--el-box-shadow-light);
}
.chat-input:focus-within {
  border-color: var(--el-color-primary);
}
.chat-input__textarea {
  display: block;
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  max-height: 200px;
  font: inherit;
  line-height: 1.5;
  background: transparent;
  color: var(--el-text-color-primary);
}
.chat-input__textarea::placeholder {
  color: var(--el-text-color-placeholder);
}
.chat-input__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}
.chat-input__counter {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
