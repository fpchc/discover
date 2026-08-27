<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import type { AssistantRecord, UploadedFile } from '@/api/types'
import AssistantMenu from '@/components/chat/AssistantMenu.vue'
import AppIcon from '@/components/common/AppIcon.vue'
import { useFileUpload } from '@/composables/useFileUpload'
import { FEATURE_FILES } from '@/config/env'

const props = defineProps<{
  /** 发送中：隐藏发送、显示「停止」 */
  disabled: boolean
  /** query 长度上限（对齐后端） */
  maxLength: number
  /** 助手目录（专家，供输入卡内 AssistantMenu 选择） */
  assistants: AssistantRecord[]
  /** 当前选择的助手（专家 id / 'generic'） */
  selectedAssistantId: string
}>()

const emit = defineEmits<{
  send: [text: string]
  stop: []
  /** 助手选择变更 → 下一次 /chat-messages 生效 */
  'assistant-change': [id: string]
}>()

const text = ref<string>('')
const composing = ref<boolean>(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const { files, uploading, accept, addFiles, remove, filePreviewUrl } = useFileUpload()

const canSend = computed<boolean>(
  () => !props.disabled && text.value.trim() !== '' && text.value.length <= props.maxLength,
)

const attachDisabled = computed<boolean>(() => props.disabled || uploading.value)

function isImage(file: UploadedFile): boolean {
  return file.media_type.startsWith('image/')
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function openPreview(file: UploadedFile): void {
  window.open(filePreviewUrl(file.file_id), '_blank', 'noopener')
}

async function handleFileChange(event: Event): Promise<void> {
  // 运行时边界：DOM 事件 target 收窄为 file input
  const input = event.target as HTMLInputElement
  const selected = input.files
  if (selected === null || selected.length === 0) return
  const list: File[] = [...selected]
  input.value = ''
  await addFiles(list)
}

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
    <div v-if="files.length > 0" class="input__files">
      <div v-for="file in files" :key="file.file_id" class="input__file">
        <img
          v-if="isImage(file)"
          class="input__file-thumb"
          :src="filePreviewUrl(file.file_id)"
          alt=""
          loading="lazy"
          @click="openPreview(file)"
        />
        <span v-else class="input__file-icon"><AppIcon name="file" :size="16" /></span>
        <div class="input__file-meta">
          <span class="input__file-name">{{ file.name }}</span>
          <span class="input__file-size">{{ formatBytes(file.size_bytes) }}</span>
        </div>
        <a
          class="input__file-action"
          :href="filePreviewUrl(file.file_id)"
          target="_blank"
          rel="noopener"
          title="预览"
        >
          <AppIcon name="external" :size="14" />
        </a>
        <a
          class="input__file-action"
          :href="filePreviewUrl(file.file_id)"
          :download="file.name"
          title="下载"
        >
          <AppIcon name="download" :size="14" />
        </a>
        <el-button
          class="input__file-remove"
          link
          circle
          size="small"
          title="移除"
          @click="remove(file.file_id)"
        >
          <AppIcon name="x" :size="13" />
        </el-button>
      </div>
    </div>

    <textarea
      ref="textareaRef"
      v-model="text"
      class="input__textarea"
      :maxlength="maxLength"
      :placeholder="disabled ? '正在生成回复…' : '发送消息，和助手对话'"
      rows="1"
      @input="resize"
      @keydown="handleKeydown"
      @compositionstart="composing = true"
      @compositionend="composing = false"
    />
    <input
      ref="fileInputRef"
      class="input__file-input"
      type="file"
      multiple
      :accept="accept"
      @change="handleFileChange"
    />
    <div class="input__footer">
      <AssistantMenu
        class="input__menu"
        :assistants="assistants"
        :selected-assistant-id="selectedAssistantId"
        :disabled="disabled"
        @select="emit('assistant-change', $event)"
      />
      <div class="input__side">
        <el-button
          v-if="FEATURE_FILES"
          class="input__attach"
          link
          circle
          :disabled="attachDisabled"
          title="上传文件"
          @click="fileInputRef?.click()"
        >
          <template #icon><AppIcon name="paperclip" :size="16" /></template>
        </el-button>
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
.input__file-input {
  display: none;
}

/* ---- 已上传文件 ---- */
.input__files {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.input__file {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-2);
}
.input__file-thumb {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  object-fit: cover;
  cursor: pointer;
}
.input__file-icon {
  flex-shrink: 0;
  display: inline-flex;
  color: var(--brand-2);
}
.input__file-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.input__file-name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-1);
}
.input__file-size {
  font-size: 11px;
  color: var(--text-3);
}
.input__file-action {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  color: var(--text-3);
  transition: color 0.15s ease;
}
.input__file-action:hover {
  color: var(--text-1);
}
.input__file-remove {
  flex-shrink: 0;
  color: var(--text-3);
}
.input__file-remove:hover {
  color: var(--el-color-danger);
}

.input__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
.input__menu {
  flex-shrink: 0;
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
.input__attach {
  color: var(--text-3);
}
.input__attach:hover:not(.is-disabled) {
  color: var(--text-1);
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
  .input {
    border-radius: 16px;
    padding: 10px 14px 8px;
  }
  .input__file-name {
    max-width: 120px;
  }
}
</style>
