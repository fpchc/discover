/**
 * 文件上传（ChatInput 单消费者，组件局部状态；API.md §2）。
 * 上传前先拉 GET /files/upload 拿限制做本地校验（扩展名 + 大小），减少无效上传；
 * 上传成功后文件进入会话内列表，支持预览 / 下载（GET /files/{id}/preview）。
 * 后端 ChatMessageRequest.files 暂不处理，文件不挂到对话消息。
 */
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { mapHttpError } from '@/api/errors'
import { fetchUploadConfig, filePreviewUrl, uploadFile } from '@/api/files'
import type { UploadConfig, UploadedFile } from '@/api/types'

export function useFileUpload() {
  const config = ref<UploadConfig | null>(null)
  const files = ref<UploadedFile[]>([])
  const uploading = ref<boolean>(false)

  /** 文件选择 accept 串（如 ".png,.pdf,…"）；config 未加载时为空串 = 不过滤 */
  const accept = computed<string>(() =>
    config.value === null ? '' : config.value.file_type_limit.map((ext) => `.${ext}`).join(','),
  )

  /** 本地校验失败返回可读文案；通过返回 null */
  function validate(file: File): string | null {
    const cfg = config.value
    if (cfg === null) return null
    const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
    if (cfg.file_type_limit.length > 0 && !cfg.file_type_limit.includes(ext)) {
      return `不支持 .${ext} 格式`
    }
    if (file.size > cfg.file_size_limit) {
      return `文件超过 ${Math.round(cfg.file_size_limit / 1024 / 1024)} MB 上限`
    }
    return null
  }

  async function loadConfig(): Promise<void> {
    try {
      config.value = await fetchUploadConfig()
    } catch {
      // 配置拉取失败不阻塞输入；上传前 validate 跳过限制（config 为 null）
    }
  }

  async function addFiles(fileList: readonly File[]): Promise<void> {
    for (const file of fileList) {
      const invalid = validate(file)
      if (invalid !== null) {
        ElMessage.warning(invalid)
        continue
      }
      uploading.value = true
      try {
        const uploaded = await uploadFile(file)
        files.value = [...files.value, uploaded]
        ElMessage.success(`已上传 ${uploaded.name}`)
      } catch (error) {
        ElMessage.error(mapHttpError(error).message)
      } finally {
        uploading.value = false
      }
    }
  }

  function remove(fileId: string): void {
    files.value = files.value.filter((file) => file.file_id !== fileId)
  }

  onMounted(() => {
    void loadConfig()
  })

  return { files, uploading, accept, validate, addFiles, remove, filePreviewUrl }
}
