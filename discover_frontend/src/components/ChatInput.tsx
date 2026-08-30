import { ArrowUp, Check, File, Paperclip, Sparkles, Square, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { FEATURE_FILES } from '@/env'
import { useFileUpload } from '@/hooks/useFileUpload'
import { cn } from '@/lib/utils'
import { GENERIC_ASSISTANT_ID } from '@/stores/assistants'
import type { AssistantRecord, UploadedFile } from '@/types'

/**
 * 悬浮输入区（composer）：输入卡上方平铺全部专家助手胶囊 + 多行 textarea
 * （Enter 发送 / Shift+Enter 换行 / IME 守卫）+ 文件上传 + 发送/停止钮，
 * 底部附免责声明与快捷键提示。整块（胶囊行 + 输入卡）随主区底部固定。
 * 纯展示 + 事件上报，状态由 App 编排托管。
 */
interface ChatInputProps {
  /** 发送中：隐藏发送、显示「停止」 */
  disabled: boolean
  /** query 长度上限（对齐后端） */
  maxLength: number
  /** 助手目录（专家，平铺胶囊来源；目录内 'generic' 项过滤） */
  assistants: AssistantRecord[]
  /** 当前选择的助手（专家 id；空串 / 未知 id 按默认处理） */
  selectedAssistantId: string
  onSend: (text: string) => void
  onStop: () => void
  /** 助手选择变更 → 下一次 /chat-messages 生效 */
  onAssistantChange: (id: string) => void
}

function isImage(file: UploadedFile): boolean {
  return file.media_type.startsWith('image/')
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export function ChatInput({
  disabled,
  maxLength,
  assistants,
  selectedAssistantId,
  onSend,
  onStop,
  onAssistantChange,
}: ChatInputProps) {
  const [text, setText] = useState('')
  const composingRef = useRef(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { files, uploading, accept, addFiles, remove, filePreviewUrl } = useFileUpload()

  /** 平铺胶囊 = 专家目录（过滤通用项；未选中任何专家即默认） */
  const expertList = assistants.filter((item) => item.id !== GENERIC_ASSISTANT_ID)

  const canSend = !disabled && text.trim() !== '' && text.length <= maxLength
  const attachDisabled = disabled || uploading

  function openPreview(file: UploadedFile): void {
    window.open(filePreviewUrl(file.file_id), '_blank', 'noopener')
  }

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>): Promise<void> {
    const selected = event.target.files
    if (selected === null || selected.length === 0) return
    const list: File[] = [...selected]
    event.target.value = ''
    await addFiles(list)
  }

  function resize(): void {
    const el = textareaRef.current
    if (el === null) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  function submit(): void {
    if (disabled || composingRef.current) return
    const trimmed = text.trim()
    if (trimmed === '' || trimmed.length > maxLength) return
    onSend(trimmed)
    setText('')
    requestAnimationFrame(resize)
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>): void {
    // Enter 发送、Shift+Enter 换行（合成输入中不触发）
    if (event.key === 'Enter' && !event.shiftKey && !composingRef.current) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <>
      {/* 平铺助手胶囊行：输入卡上方，随输入区固定；选中高亮，流式中禁用 */}
      {expertList.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          {expertList.map((item) => {
            const selected = item.id === selectedAssistantId
            return (
              <button
                key={item.id}
                type="button"
                disabled={disabled}
                title={item.description}
                // 再次点击已选中的胶囊 = 取消选择，退回默认「通用对话」（generic 不在平铺列表里）
                onClick={() => onAssistantChange(selected ? GENERIC_ASSISTANT_ID : item.id)}
                className={cn(
                  'inline-flex h-7 cursor-pointer items-center gap-1 rounded-full border pl-2 pr-2.5 text-[12px] transition-colors',
                  selected
                    ? 'border-brand-2/50 bg-brand-2/10 font-medium text-brand-2'
                    : 'border-border bg-surface-2/60 text-text-2 hover:border-brand-2/40 hover:bg-surface-hover hover:text-text-1',
                  disabled && 'cursor-not-allowed opacity-60',
                )}
              >
                <Sparkles className="size-3 flex-shrink-0" />
                {item.name}
                {selected && <Check className="size-3 flex-shrink-0" />}
              </button>
            )
          })}
        </div>
      )}

      <div className={cn('input-panel', disabled && 'is-disabled')}>
        {/* 已上传文件 */}
        {files.length > 0 && (
          <div className="mb-2.5 flex flex-wrap gap-2">
            {files.map((file) => (
              <div
                key={file.file_id}
                className="flex items-center gap-2 rounded-[10px] border border-border bg-surface-2 p-1.5"
              >
                {isImage(file) ? (
                  <button
                    type="button"
                    className="flex-shrink-0 cursor-pointer overflow-hidden rounded-md"
                    onClick={() => openPreview(file)}
                  >
                    <img
                      className="h-8 w-8 object-cover"
                      src={filePreviewUrl(file.file_id)}
                      alt=""
                      loading="lazy"
                    />
                  </button>
                ) : (
                  <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center text-brand-2">
                    <File className="h-4 w-4" />
                  </span>
                )}
                <div className="flex min-w-0 flex-col">
                  <span className="max-w-44 truncate text-xs text-text-1">{file.name}</span>
                  <span className="text-[11px] text-text-3">{formatBytes(file.size_bytes)}</span>
                </div>
                <button
                  type="button"
                  className="ml-1 flex h-6 w-6 items-center justify-center rounded-full text-text-3 hover:bg-surface-hover hover:text-destructive"
                  title="移除"
                  onClick={() => remove(file.file_id)}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={text}
          onChange={(event) => {
            setText(event.target.value)
            resize()
          }}
          onKeyDown={handleKeyDown}
          onCompositionStart={() => {
            composingRef.current = true
          }}
          onCompositionEnd={() => {
            composingRef.current = false
          }}
          rows={1}
          maxLength={maxLength}
          placeholder={disabled ? '正在生成回复…' : '发送消息，和助手对话'}
          className="block max-h-50 w-full resize-none bg-transparent text-sm leading-relaxed text-text-1 outline-none placeholder:text-text-3"
        />
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={accept}
          className="hidden"
          onChange={(event) => void handleFileChange(event)}
        />

        <div className="mt-2 flex items-center justify-end gap-2">
          {FEATURE_FILES && (
            <button
              type="button"
              disabled={attachDisabled}
              title="上传文件"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-text-3 transition-colors hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => fileInputRef.current?.click()}
            >
              <Paperclip className="h-4 w-4" />
            </button>
          )}
          <span className="font-mono text-xs tabular-nums text-text-3">
            {text.length}/{maxLength}
          </span>
          {disabled ? (
            <button
              type="button"
              title="停止生成"
              onClick={onStop}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-surface-2 text-text-1 transition-colors hover:bg-surface-hover"
            >
              <Square className="h-3 w-3 fill-current" />
            </button>
          ) : (
            <button
              type="button"
              title="发送"
              disabled={!canSend}
              onClick={submit}
              className={cn(
                'flex h-9 w-9 items-center justify-center rounded-full text-white shadow-glow-brand transition-all',
                canSend
                  ? 'bg-brand-gradient hover:scale-105 hover:shadow-[0_8px_26px_rgba(139,92,246,0.5)]'
                  : 'bg-surface-hover text-text-3 shadow-none',
              )}
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      <p className="mt-2.5 text-center text-xs text-text-3">内容由 AI 生成，请仔细甄别</p>
    </>
  )
}
