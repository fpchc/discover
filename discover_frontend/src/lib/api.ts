/**
 * HTTP 唯一出口（CLAUDE.md 第 4 节）：axios 实例 + 对话 / 历史 / 文件 / 助手接口封装。
 * 禁止组件内裸 fetch / 裸 axios（SSE 读取除外，见 lib/stream.ts）。
 * 注意：不得在实例默认头里写死 Content-Type —— axios 会据此对 FormData 做
 * JSON.stringify(formDataToJSON(data))，导致文件上传变成 JSON 体、后端 422。
 * 让 axios 按请求体自动推断：JSON 对象 → application/json，FormData → 浏览器补 multipart。
 */
import axios, { type InternalAxiosRequestConfig, isAxiosError } from 'axios'
import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '@/env'
import {
  clearStoredTokens,
  readStoredRefreshToken,
  readStoredToken,
  writeStoredRefreshToken,
  writeStoredToken,
} from '@/lib/auth'
import type {
  AccountRecord,
  AccountUsage,
  AssistantRecord,
  AvatarConfig,
  BlockingChatResponse,
  ChangePasswordRequest,
  ChatRequest,
  ConversationRecord,
  LoginRequest,
  LoginResponse,
  MessageRecord,
  UpdateAccountRequest,
  UploadConfig,
  UploadedFile,
  UsageDaily,
} from '@/types'

export const httpClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
})

// ===================== 认证（ACCOUNT_API.md §1） =====================

/**
 * 请求拦截器：所有受保护请求自动注入 `Authorization: Bearer <token>`。
 * 令牌从 localStorage 读取（lib/auth.ts 为唯一事实源）；未登录不发头，
 * 由后端对缺令牌返回 401。
 */
httpClient.interceptors.request.use((config) => {
  const token = readStoredToken()
  if (token !== null) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

/**
 * 全局 401 → 会话过期回调（由 main.tsx 注册到 auth store 的 expire）。
 * 用注册而非直接 import 避免 api ↔ auth 循环依赖。触发条件收窄为「刷新失败 /
 * 无刷新令牌」——401 先走刷新重放，重放成功即不跳登录页。
 */
let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

/** 认证端点自身不做「401 → 刷新重试」（防递归：login=密码错、refresh=刷新令牌失效、logout=访问令牌已过期） */
const isAuthEndpoint = (url: string): boolean => url.startsWith('/auth/')

/** 并发 401 单飞：同一时刻只发起一次刷新，其余 401 等待共用结果（防刷新风暴） */
let refreshPromise: Promise<string | null> | null = null

/**
 * 用刷新令牌换新令牌对（POST /auth/refresh；轮换制，旧刷新令牌作废）。
 * 成功后 access + refresh 成对写回 localStorage；失败返回 null（由拦截器统一清令牌 + 过期）。
 */
async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise !== null) return refreshPromise
  refreshPromise = (async () => {
    const refresh = readStoredRefreshToken()
    if (refresh === null) return null
    try {
      const data = await refreshToken(refresh)
      writeStoredToken(data.token)
      writeStoredRefreshToken(data.refresh_token)
      return data.token
    } catch {
      return null
    }
  })().finally(() => {
    refreshPromise = null
  })
  return refreshPromise
}

/** axios 内部扩展字段 `_retry`（标记该请求已刷新重放）未在公开类型内暴露，运行时边界收窄 */
interface RetriableRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
}

httpClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (!isAxiosError(error) || error.response?.status !== 401) {
      return Promise.reject(error)
    }
    const url = error.config?.url ?? ''
    // 认证端点 401 直接放行：调用方按各自语义处理（登录失败 / 刷新令牌失效 / 登出幂等）
    if (isAuthEndpoint(url)) {
      return Promise.reject(error)
    }
    // 受保护端点 401 → 刷新令牌续期并重放一次；重放仍 401 / 刷新失败 → 会话过期
    const config = error.config as RetriableRequestConfig | undefined
    if (config !== undefined && config._retry !== true) {
      config._retry = true
      const fresh = await refreshAccessToken()
      if (fresh !== null) {
        config.headers.set('Authorization', `Bearer ${fresh}`)
        return httpClient.request(config)
      }
    }
    // 无刷新令牌 / 刷新失败 / 重放后仍 401：清本地令牌并触发全局过期（回登录页）
    clearStoredTokens()
    if (unauthorizedHandler !== null) unauthorizedHandler()
    return Promise.reject(error)
  },
)

/** 手机号 + 密码登录，成功返回令牌对与账号基础信息（ACCOUNT_API.md §1.1） */
export async function login(params: LoginRequest): Promise<LoginResponse> {
  const { data } = await httpClient.post<LoginResponse>('/auth/login', params)
  return data
}

/** 刷新令牌换新令牌对（POST /auth/refresh；轮换制，旧刷新令牌作废，Redis 权威） */
export async function refreshToken(refreshTokenValue: string): Promise<LoginResponse> {
  const { data } = await httpClient.post<LoginResponse>('/auth/refresh', {
    refresh_token: refreshTokenValue,
  })
  return data
}

/**
 * 服务端登出（POST /auth/logout；204）：作废当前访问 + 刷新令牌（DEL 幂等，无 key 也 204）。
 * access / refresh 显式传入：登出需先清本地再调后端，不能依赖拦截器读 localStorage 的时机；
 * 访问令牌已过期（Redis 已清）时后端仍返回 204，失败不阻塞本地登出。
 */
export async function logout(
  accessToken: string | null,
  refreshTokenValue: string | null,
): Promise<void> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (accessToken !== null) {
    headers.Authorization = `Bearer ${accessToken}`
  }
  await httpClient.post('/auth/logout', { refresh_token: refreshTokenValue ?? '' }, { headers })
}

/** 当前登录账号信息（ACCOUNT_API.md §1.2；需认证） */
export async function fetchMe(): Promise<AccountRecord> {
  const { data } = await httpClient.get<AccountRecord>('/users/me')
  return data
}

/** 当前账号 token 用量（GET /users/me/usage；需认证） */
export async function fetchAccountUsage(): Promise<AccountUsage> {
  const { data } = await httpClient.get<AccountUsage>('/users/me/usage')
  return data
}

/** 当前账号近 N 日用量序列（GET /users/me/usage/daily?days=；趋势图数据源） */
export async function fetchUsageDaily(days = 30): Promise<UsageDaily> {
  const { data } = await httpClient.get<UsageDaily>('/users/me/usage/daily', {
    params: { days },
  })
  return data
}

/** 头像上传限制（GET /users/me/avatar-config；供前端本地校验输入） */
export async function fetchAvatarConfig(): Promise<AvatarConfig> {
  const { data } = await httpClient.get<AvatarConfig>('/users/me/avatar-config')
  return data
}

/** 更新当前账号资料（PATCH /users/me；当前仅昵称） */
export async function updateAccountName(name: string): Promise<AccountRecord> {
  const body: UpdateAccountRequest = { name }
  const { data } = await httpClient.patch<AccountRecord>('/users/me', body)
  return data
}

/** 更换头像（POST /users/me/avatar，multipart 字段 file；返回更新后账号） */
export async function uploadAvatar(file: File): Promise<AccountRecord> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await httpClient.post<AccountRecord>('/users/me/avatar', form)
  return data
}

/** 修改密码（POST /users/me/password；必须携带原密码） */
export async function changePassword(req: ChangePasswordRequest): Promise<AccountRecord> {
  const { data } = await httpClient.post<AccountRecord>('/users/me/password', req)
  return data
}

/**
 * 头像展示 URL：账号 avatar 存相对路径（/files/{id}/preview），拼上 API base；
 * 绝对地址（http(s)）直接透传（预留外部头像源）。
 */
export function avatarUrl(avatar: string | null): string | null {
  if (avatar === null || avatar === '') return null
  if (/^https?:\/\//i.test(avatar)) return avatar
  return `${API_BASE_URL}${avatar}`
}

// ===================== 对话（API.md §4） =====================

export interface SendChatMessageParams {
  query: string
  /** 空串 = 新建会话；续聊必带后端回传的会话 ID */
  conversationId: string
  /** 当前选中的助手 id；空串 = 不显式选择（首轮走通用 / 续聊沿用已绑定） */
  agentId: string
  signal: AbortSignal
}

/** 组装对话请求体；agent_id 为空时省略（避免向后端传空串） */
function buildChatRequest(
  params: SendChatMessageParams,
  responseMode: 'streaming' | 'blocking',
): ChatRequest {
  return {
    query: params.query,
    response_mode: responseMode,
    conversation_id: params.conversationId,
    ...(params.agentId !== '' ? { agent_id: params.agentId } : {}),
  }
}

/**
 * 发起流式对话请求。
 * SSE 必须用 fetch + ReadableStream（POST 语义，不能用 EventSource）；
 * 返回未消费的 Response，交由 lib/stream.ts 读取帧。
 * 走裸 fetch，不走 axios 拦截器，故在此显式注入 Bearer 令牌。
 */
export function sendChatMessage(params: SendChatMessageParams): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = readStoredToken()
  if (token !== null) {
    headers.Authorization = `Bearer ${token}`
  }
  return fetch(`${API_BASE_URL}/chat-messages`, {
    method: 'POST',
    headers,
    body: JSON.stringify(buildChatRequest(params, 'streaming')),
    signal: params.signal,
  })
}

/**
 * 阻塞模式对话（axios 普通 HTTP 出口）。
 * 用于流式失败的兜底重试（受 VITE_FEATURE_BLOCKING_FALLBACK 开关控制）；
 * 返回后端 chat-messages JSON。
 */
export async function sendChatMessageBlocking(
  params: SendChatMessageParams,
): Promise<BlockingChatResponse> {
  const { data } = await httpClient.post<BlockingChatResponse>(
    '/chat-messages',
    buildChatRequest(params, 'blocking'),
    { signal: params.signal },
  )
  return data
}

// ===================== 会话历史（API.md §1） =====================

const DEFAULT_LIMIT = 100

export async function fetchConversations(
  limit = DEFAULT_LIMIT,
  offset = 0,
): Promise<ConversationRecord[]> {
  const { data } = await httpClient.get<ConversationRecord[]>('/conversations', {
    params: { limit, offset },
  })
  return data
}

export async function fetchMessages(
  conversationId: string,
  limit = DEFAULT_LIMIT,
  offset = 0,
): Promise<MessageRecord[]> {
  const { data } = await httpClient.get<MessageRecord[]>(
    `/conversations/${conversationId}/messages`,
    { params: { limit, offset } },
  )
  return data
}

/** 删除会话（204 成功；404 视为已删除，由调用方按「已删除」处理） */
export async function deleteConversation(conversationId: string): Promise<void> {
  await httpClient.delete(`/conversations/${conversationId}`)
}

// ===================== 助手目录（API.md §3） =====================

export async function fetchAssistants(): Promise<AssistantRecord[]> {
  const { data } = await httpClient.get<AssistantRecord[]>('/assistants')
  return data
}

// ===================== 文件（API.md §2） =====================

export async function fetchUploadConfig(): Promise<UploadConfig> {
  const { data } = await httpClient.get<UploadConfig>('/files/upload')
  return data
}

/**
 * 上传文件（multipart/form-data，字段名 file）。
 * 传入 FormData 时依赖 axios 自动推断 Content-Type（前提：实例默认头未写死
 * application/json，见 httpClient），由浏览器补 multipart boundary，无需手动设置请求头。
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
