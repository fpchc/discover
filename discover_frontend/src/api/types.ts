/**
 * 后端契约类型（映射 discover_backend pydantic 模型）。
 * 禁止在组件内散落重复定义；新契约字段先在此对齐。
 *
 * 边界已确认（discover_backend/src/platform_engine/api/routes_chat.py + docs/API.md）：
 * SSE 判别帧共 7 种：message / message_end / ping / error 与思考三帧
 * thinking_started / thinking_delta / thinking_ended。message 帧 answer 为正文
 * 纯文本增量；thinking_* 帧携带思考过程，独立于正文。tool_call_* / artifact_ready
 * 仍为后端内部事件，不外泄到正文。
 *
 * 历史接口（API.md §1）：会话列表 / 消息流 / 用量汇总均由后端提供，前端不落本地。
 */

// ---- 历史接口（API.md §1） ----

/** 会话记录（GET /conversations；会话列表唯一事实源） */
export interface ConversationRecord {
  conversation_id: string
  agent_id: string | null
  model_provider: string | null
  model_id: string | null
  /** 会话标题（首条 query 截断，50 字内） */
  name: string
  /** 摘要（预留，当前为 null） */
  summary: string | null
  status: 'active' | 'closed'
  dialogue_count: number
  created_at: string
  updated_at: string
}

/** 单条回合记录（GET /conversations/{id}/messages；query + answer 同行） */
export interface MessageRecord {
  message_id: string
  conversation_id: string
  agent_id: string | null
  provider: string | null
  model: string | null
  query: string
  answer: string | null
  /** 思考内容（审计用途；前端可折叠展示） */
  thinking: string | null
  status: 'normal' | 'error'
  error: string | null
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_read_tokens: number
  cached_write_tokens: number
  created_at: string
  updated_at: string
}

/** 会话用量汇总（GET /conversations/{id}/usage） */
export interface ConversationUsage {
  message_count: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cached_read_tokens: number
  cached_write_tokens: number
}

// ---- 文件接口（API.md §2） ----

/** 上传限制配置（GET /files/upload；前端本地校验用） */
export interface UploadConfig {
  file_size_limit: number
  file_type_limit: string[]
}

/** 上传文件记录（POST /files/upload 响应） */
export interface UploadedFile {
  file_id: string
  name: string
  media_type: string
  size_bytes: number
  created_at: string
}

export type MessageRole = 'user' | 'assistant'

/** 消息渲染态：流式中 / 完成 / 错误 */
export type MessageStatus = 'streaming' | 'done' | 'error'

/** 用量信息（message_end.metadata.usage；字段可选以容忍后端缺省；API.md §3 扩为 5 键） */
export interface UsageInfo {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  cached_read_tokens?: number
  cached_write_tokens?: number
}

/** 单条对话消息（流式过程中由 store 按当前消息增量拼装） */
export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  created_at: string
  status: MessageStatus
  /** 错误态展示文案（仅 status === 'error'） */
  errorMessage?: string
  usage?: UsageInfo
  /** 思考过程（thinking_started → thinking_delta 累积；仅助手消息） */
  thinking?: string
  /** 思考分区状态：thinking=进行中（展开）/ done=已结束（收起显示时长） */
  thinkingStatus?: 'thinking' | 'done'
  /** 末次思考耗时 ms（thinking_ended.duration_ms） */
  thinkingDurationMs?: number
}

/** 对话请求体（对齐后端 ChatMessageRequest） */
export interface ChatRequest {
  query: string
  response_mode: 'streaming' | 'blocking'
  conversation_id: string
}

/** blocking 模式响应（对齐后端 ChatMessageResponse） */
export interface BlockingChatResponse {
  message_id: string
  mode: 'chat'
  answer: string
  metadata: {
    usage?: UsageInfo
  }
  conversation_id: string
  created_at: number
}

// ---- SSE 帧契约（对齐 CLAUDE.md 第 5 节；后端判别联合，不可臆造） ----

interface SseFrameBase {
  event: string
  conversation_id: string
  message_id: string
}

/** message → 正文增量，追加到当前回复 */
export interface SseMessageFrame extends SseFrameBase {
  event: 'message'
  answer: string
  created_at: number
}

/** message_end → 收尾帧，含 usage；流结束，无 [DONE] */
export interface SseMessageEndFrame extends SseFrameBase {
  event: 'message_end'
  metadata: {
    usage?: UsageInfo
  }
  created_at: number
}

/** thinking_started → 打开思考分区（可折叠） */
export interface SseThinkingStartedFrame extends SseFrameBase {
  event: 'thinking_started'
  created_at: number
}

/** thinking_delta → 思考增量，追加到思考分区 */
export interface SseThinkingDeltaFrame extends SseFrameBase {
  event: 'thinking_delta'
  content: string
  created_at: number
}

/** thinking_ended → 思考结束，含耗时 ms；折叠思考分区 */
export interface SseThinkingEndedFrame extends SseFrameBase {
  event: 'thinking_ended'
  duration_ms: number
  created_at: number
}

/** ping → 心跳，忽略 */
export interface SsePingFrame {
  event: 'ping'
}

/** error → 错误帧 {status, code, message} */
export interface SseErrorFrame {
  event: 'error'
  status: number
  code: string
  message: string
}

/** 流式事件判别联合 */
export type SseStreamFrame =
  | SseMessageFrame
  | SseMessageEndFrame
  | SseThinkingStartedFrame
  | SseThinkingDeltaFrame
  | SseThinkingEndedFrame
  | SsePingFrame
  | SseErrorFrame
