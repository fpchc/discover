/**
 * 后端契约类型（映射 discover_backend pydantic 模型）。
 * 禁止在组件内散落重复定义；新契约字段先在此对齐。
 *
 * 边界已确认（discover_backend/src/platform_engine/api/routes_chat.py）：
 * SSE 判别帧仅 message / message_end / ping / error 四种；message 帧 answer 为
 * 纯文本增量（thinking / tool_call / artifact 均为内部事件，不外泄到正文），
 * 故 M2–M4 高级事件在 v1 保持纯正文展示。
 */

/** 会话元数据（仅本地持久化；消息全文由后端持有） */
export interface ConversationMeta {
  conversation_id: string
  title: string
  created_at: string
  updated_at: string
}

export type MessageRole = 'user' | 'assistant'

/** 消息渲染态：流式中 / 完成 / 错误 */
export type MessageStatus = 'streaming' | 'done' | 'error'

/** 用量信息（message_end.metadata.usage；字段可选以容忍后端缺省） */
export interface UsageInfo {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
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
export type SseStreamFrame = SseMessageFrame | SseMessageEndFrame | SsePingFrame | SseErrorFrame
