/**
 * 环境配置唯一入口：将 VITE_* 原始字符串收窄为带默认值的类型化常量。
 * 禁止在组件 / lib / hooks 中直接读取 import.meta.env。
 */
export type AppEnv = 'development' | 'test' | 'production'

function parseAppEnv(value: string | undefined): AppEnv {
  if (value === 'development' || value === 'test' || value === 'production') {
    return value
  }
  return 'development'
}

function parsePositiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? '', 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function parseBool(value: string | undefined, fallback: boolean): boolean {
  if (value === 'true') return true
  if (value === 'false') return false
  return fallback
}

/** 当前应用环境，用于 UI 徽标 / 日志区分（与 vite mode 正交） */
export const APP_ENV: AppEnv = parseAppEnv(import.meta.env.VITE_APP_ENV)

/** 后端 API base（含 /api/v1 前缀）；同源部署时由 vite / nginx 代理 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || '/api/v1'

/** SSE 流式请求整体超时（毫秒）；默认 15 分钟，长思考/工具调用流远超 5 分钟 */
export const SSE_TIMEOUT_MS: number = parsePositiveInt(import.meta.env.VITE_SSE_TIMEOUT_MS, 900_000)

/** 普通 HTTP（blocking）请求超时（毫秒） */
export const REQUEST_TIMEOUT_MS: number = parsePositiveInt(
  import.meta.env.VITE_REQUEST_TIMEOUT_MS,
  30_000,
)

/** 用户 query 长度上限（对齐后端 ChatMessageRequest.max_length） */
export const CHAT_QUERY_MAX: number = parsePositiveInt(import.meta.env.VITE_CHAT_QUERY_MAX, 4000)

/** 会话标题取首条用户消息的最大字符数 */
export const CONVERSATION_TITLE_MAX: number = parsePositiveInt(
  import.meta.env.VITE_CONVERSATION_TITLE_MAX,
  20,
)

/** 功能开关 */
export const FEATURE_THINKING: boolean = parseBool(import.meta.env.VITE_FEATURE_THINKING, true)
export const FEATURE_TOOL_CALLS: boolean = parseBool(import.meta.env.VITE_FEATURE_TOOL_CALLS, true)
export const FEATURE_ARTIFACTS: boolean = parseBool(import.meta.env.VITE_FEATURE_ARTIFACTS, true)
export const FEATURE_FILES: boolean = parseBool(import.meta.env.VITE_FEATURE_FILES, true)

/** 阻塞兜底开关（流式失败后可切 blocking 模式重试） */
export const FEATURE_BLOCKING_FALLBACK: boolean = parseBool(
  import.meta.env.VITE_FEATURE_BLOCKING_FALLBACK,
  true,
)
