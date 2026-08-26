/**
 * 文件接口封装（API.md §2）。
 * 上传前先 GET /files/upload 拿限制做本地校验；预览为流式 inline（浏览器直接展示）。
 */
import { API_BASE_URL } from '@/config/env'
import { httpClient } from './client'
import type { UploadConfig, UploadedFile } from './types'

export async function fetchUploadConfig(): Promise<UploadConfig> {
  const { data } = await httpClient.get<UploadConfig>('/files/upload')
  return data
}

/**
 * 上传文件（multipart/form-data，字段名 file）。
 * 传入 FormData 时依赖 axios 自动推断 Content-Type（前提：实例默认头未写死
 * application/json，见 client.ts），由浏览器补 multipart boundary，无需手动设置请求头。
 */
export async function uploadFile(file: File): Promise<UploadedFile> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await httpClient.post<UploadedFile>('/files/upload', form)
  return data
}

/** 文件预览 / 下载共用 URL（服务端 inline，加 download 属性才触发下载） */
export function filePreviewUrl(fileId: string): string {
  return `${API_BASE_URL}/files/${fileId}/preview`
}
