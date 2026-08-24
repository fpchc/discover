/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 应用环境（与 vite mode 正交）：development | test | production */
  readonly VITE_APP_ENV: string
  /** 后端 API base URL（含 /api/v1 前缀） */
  readonly VITE_API_BASE_URL: string
  /** SSE 流式请求整体超时（毫秒） */
  readonly VITE_SSE_TIMEOUT_MS: string
  /** 用户 query 长度上限 */
  readonly VITE_CHAT_QUERY_MAX: string
  /** 普通 HTTP 请求超时（毫秒） */
  readonly VITE_REQUEST_TIMEOUT_MS: string
  /** dev 代理目标后端（仅 vite dev 使用） */
  readonly VITE_PROXY_TARGET: string
  /** 功能开关：思考过程 / 工具调用 / 产物链接 */
  readonly VITE_FEATURE_THINKING: string
  readonly VITE_FEATURE_TOOL_CALLS: string
  readonly VITE_FEATURE_ARTIFACTS: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
