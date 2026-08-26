/**
 * 统一错误映射（CLAUDE.md 第 4 节）：HTTP 状态码 + SSE error 帧 → 前端可读文案。
 * 集中一处维护，禁止组件内散落文案。
 */
import { isAxiosError } from 'axios'

export interface AppError {
  status: number | null
  code: string
  message: string
}

const FALLBACK_NETWORK_MESSAGE = '网络请求失败，请稍后重试'
const FALLBACK_HTTP_MESSAGE = '请求失败，请稍后重试'

const STATUS_MESSAGES: Record<number, string> = {
  400: '请求参数有误',
  401: '未授权，请刷新后重试',
  403: '无权限访问',
  404: '会话不存在或已失效',
  429: '请求过于频繁，请稍后重试',
  500: '服务内部错误',
  502: '网关错误，请稍后重试',
  503: '服务暂不可用，请稍后重试',
}

/** SSE error 帧 {status, code, message} → AppError */
export function mapSseError(payload: unknown): AppError {
  if (typeof payload === 'object' && payload !== null) {
    // 运行时边界：JSON 反序列化结果，收窄为可读字段
    const record = payload as Record<string, unknown>
    const status = typeof record.status === 'number' ? record.status : null
    const code = typeof record.code === 'string' ? record.code : 'SSE_ERROR'
    const message = typeof record.message === 'string' ? record.message : '流式响应异常'
    return { status, code, message }
  }
  return { status: null, code: 'SSE_ERROR', message: '流式响应异常' }
}

/**
 * 从 HTTP 错误体提取可读文案。
 * 后端形状：PlatformError `{error:{category,message}}`、FastAPI `{detail}`、兜底 `{message}`。
 */
function extractBodyMessage(data: unknown): string {
  if (typeof data !== 'object' || data === null) return ''
  const record = data as Record<string, unknown>
  if (typeof record.error === 'object' && record.error !== null) {
    const error = record.error as Record<string, unknown>
    if (typeof error.message === 'string') return error.message
  }
  if (typeof record.detail === 'string') return record.detail
  if (typeof record.message === 'string') return record.message
  return ''
}

function statusFallbackMessage(status: number | null): string {
  if (status !== null && STATUS_MESSAGES[status] !== undefined) return STATUS_MESSAGES[status]
  return FALLBACK_HTTP_MESSAGE
}

/** 统一 HTTP 错误映射：axios / 原生 Error / 未知 */
export function mapHttpError(error: unknown): AppError {
  if (isAxiosError(error)) {
    const status = error.response?.status ?? null
    if (status === null) {
      return { status: null, code: 'NETWORK_ERROR', message: FALLBACK_NETWORK_MESSAGE }
    }
    const message = extractBodyMessage(error.response?.data) || statusFallbackMessage(status)
    return { status, code: `HTTP_${status}`, message }
  }
  if (error instanceof Error) {
    return {
      status: null,
      code: 'NETWORK_ERROR',
      message: error.message || FALLBACK_NETWORK_MESSAGE,
    }
  }
  return { status: null, code: 'UNKNOWN_ERROR', message: FALLBACK_NETWORK_MESSAGE }
}

/** 携带 AppError 的受控异常（fetch 非 2xx → 解析 body 后抛出，供上层按错误态处理） */
export class HttpError extends Error {
  readonly appError: AppError

  constructor(appError: AppError) {
    super(appError.message)
    this.name = 'HttpError'
    this.appError = appError
  }
}

/** 从非 2xx Response 解析后端错误体为 HttpError */
export async function readResponseError(response: Response): Promise<HttpError> {
  const status = response.status
  let message = statusFallbackMessage(status)
  try {
    const data: unknown = await response.json()
    message = extractBodyMessage(data) || message
  } catch {
    // 非 JSON body，保留状态码兜底文案
  }
  return new HttpError({ status, code: `HTTP_${status}`, message })
}

/** 流中断（未到 message_end 即断）——保留已收内容 */
export const STREAM_INTERRUPTED: AppError = {
  status: null,
  code: 'STREAM_INTERRUPTED',
  message: '连接中断，已保留已接收内容',
}

/** 超时（VITE_SSE_TIMEOUT_MS 兜底） */
export const TIMEOUT_ERROR: AppError = {
  status: null,
  code: 'TIMEOUT',
  message: '响应超时，请重试',
}
