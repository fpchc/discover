import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { fetchUploadConfig, filePreviewUrl, uploadFile } from '@/lib/api'
import { mapHttpError } from '@/lib/errors'
import type { UploadConfig, UploadedFile } from '@/types'

/**
 * 文件上传（ChatInput 单消费者，组件局部状态；API.md §2）。
 * 上传前先拉 GET /files/upload 拿限制做本地校验（扩展名 + 大小），减少无效上传；
 * 上传成功后文件进入会话内列表，支持预览 / 下载（GET /files/{id}/preview）。
 * 后端 ChatMessageRequest.files 暂不处理，文件不挂到对话消息。
 */
export interface UseFileUploadResult {
  files: UploadedFile[]
  uploading: boolean
  /** 文件选择 accept 串（如 ".png,.pdf,…"）；config 未加载时为空串 = 不过滤 */
  accept: string
  validate: (file: File) => string | null
  addFiles: (fileList: readonly File[]) => Promise<void>
  remove: (fileId: string) => void
  filePreviewUrl: (fileId: string) => string
}

export function useFileUpload(): UseFileUploadResult {
  const [config, setConfig] = useState<UploadConfig | null>(null)
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [uploading, setUploading] = useState<boolean>(false)

  const accept = useMemo<string>(
    () => (config === null ? '' : config.file_type_limit.map((ext) => `.${ext}`).join(',')),
    [config],
  )

  /** 本地校验失败返回可读文案；通过返回 null */
  function validate(file: File): string | null {
    if (config === null) return null
    const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
    if (config.file_type_limit.length > 0 && !config.file_type_limit.includes(ext)) {
      return `不支持 .${ext} 格式`
    }
    if (file.size > config.file_size_limit) {
      return `文件超过 ${Math.round(config.file_size_limit / 1024 / 1024)} MB 上限`
    }
    return null
  }

  useEffect(() => {
    let cancelled = false
    void fetchUploadConfig()
      .then((cfg) => {
        if (!cancelled) setConfig(cfg)
      })
      .catch(() => {
        // 配置拉取失败不阻塞输入；上传前 validate 跳过限制（config 为 null）
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function addFiles(fileList: readonly File[]): Promise<void> {
    for (const file of fileList) {
      const invalid = validate(file)
      if (invalid !== null) {
        toast.warning(invalid)
        continue
      }
      setUploading(true)
      try {
        const uploaded = await uploadFile(file)
        setFiles((prev) => [...prev, uploaded])
        toast.success(`已上传 ${uploaded.name}`)
      } catch (error) {
        toast.error(mapHttpError(error).message)
      } finally {
        setUploading(false)
      }
    }
  }

  function remove(fileId: string): void {
    setFiles((prev) => prev.filter((file) => file.file_id !== fileId))
  }

  return { files, uploading, accept, validate, addFiles, remove, filePreviewUrl }
}
