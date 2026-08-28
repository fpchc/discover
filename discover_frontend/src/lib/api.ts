/**
 * HTTP 唯一出口（CLAUDE.md 第 4 节）：axios 实例 + 对话 / 历史 / 文件 / 助手接口封装。
 * 禁止组件内裸 fetch / 裸 axios（SSE 读取除外，见 lib/stream.ts）。
 * 注意：不得在实例默认头里写死 Content-Type —— axios 会据此对 FormData 做
 * JSON.stringify(formDataToJSON(data))，导致文件上传变成 JSON 体、后端 422。
 * 让 axios 按请求体自动推断：JSON 对象 → application/json，FormData → 浏览器补 multipart。
 */
import axios, { isAxiosError } from 'axios'
import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '@/env'
import { readStoredToken } from '@/lib/auth'
import type {
  AccountRecord,
  AssistantRecord,
  BlockingChatResponse,
  ChatRequest,
  ConversationRecord,
  LoginRequest,
  LoginResponse,
  MessageRecord,
  UploadConfig,
  UploadedFile,
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
 * 用注册而非直接 import 避免 api ↔ auth 循环依赖。登录接口自身 401（密码错误）
 * 不触发全局过期，交由 login 调用方按登录失败处理。
 */
let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

httpClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (isAxiosError(error) && error.response?.status === 401) {
      const url = error.config?.url ?? ''
      const isLogin = url.includes('/auth/login')
      if (!isLogin && unauthorizedHandler !== null) {
        unauthorizedHandler()
      }
    }
    return Promise.reject(error)
  },
)

/** 手机号 + 密码登录，成功返回 JWT 与账号基础信息（ACCOUNT_API.md §1.1） */
export async function login(params: LoginRequest): Promise<LoginResponse> {
  const { data } = await httpClient.post<LoginResponse>('/auth/login', params)
  return data
}

/** 当前登录账号信息（ACCOUNT_API.md §1.2；需认证） */
export async function fetchMe(): Promise<AccountRecord> {
  const { data } = await httpClient.get<AccountRecord>('/users/me')
  return data
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
