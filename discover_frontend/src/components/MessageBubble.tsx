import { Copy, RotateCcw, Sparkles } from 'lucide-react'
import { motion } from 'motion/react'
import { memo, useDeferredValue, useMemo } from 'react'
import { toast } from 'sonner'
import { Markdown } from '@/components/Markdown'
import { StatusBadge } from '@/components/StatusBadge'
import { StructuredParams } from '@/components/StructuredParams'
import { ThinkingPanel } from '@/components/ThinkingPanel'
import { FEATURE_THINKING } from '@/env'
import { useThrottledValue } from '@/hooks/useThrottledValue'
import { extractLeadingParams, extractStructuredParams, stripParamBlocks } from '@/lib/structure'
import { cn } from '@/lib/utils'
import type { ChatMessage } from '@/types'

/**
 * 消息气泡（performance.md §1 React.memo 隔离）。
 * - 历史消息 props 引用不变即绝不重渲（store 不可变更新保证，见 stores/chat.ts）。
 * - 流式消息：正文经 useThrottledValue(40ms) + useDeferredValue 双重降载后渲染
 *   Markdown，高亮仅收尾后启用（performance.md §2）。
 * - 思考分区：抽取 ThinkingPanel；进行中粒子流 + shimmer，结束可折叠显示耗时。
 * - 结构化参数（视觉重构）：用户输入 / AI 回复中的「【键】值」自动解析为
 *   KV 卡片网格 / 胶囊（StructuredParams），不再露出一串 【】 字符。
 * - 状态徽章：流式阶段（深度思考 / 生成中）与完成态以 StatusBadge 呈现。
 * - 收尾后悬停浮现「复制 / 重新生成 / 已生成」操作（仅最后一条已完成消息可重新生成）。
 */
interface MessageBubbleProps {
  message: ChatMessage
  onRetry: () => void
  /** 是否可「重新生成」（仅消息流最后一条已完成助手消息；由 ChatWindow 判定） */
  canRegenerate?: boolean
}

function MessageBubbleInner({ message, onRetry, canRegenerate = false }: MessageBubbleProps) {
  const isAssistant = message.role === 'assistant'
  const streaming = message.status === 'streaming'
  // 流式期尾沿节流（40ms）合并增量 + useDeferredValue 让出主线程；收尾后直接用最终文本
  const throttledContent = useThrottledValue(message.content, 40)
  const deferredContent = useDeferredValue(throttledContent)
  const renderContent = streaming ? deferredContent : message.content
  const streamingEmpty = isAssistant && streaming && message.content === ''

  const hasThinking = FEATURE_THINKING && isAssistant && message.thinkingStatus !== undefined
  const thinkingActive = hasThinking && message.thinkingStatus === 'thinking'

  // ---- 结构化参数：用户消息解析全文；助手消息解析开头参数段（≥2 块才结构化） ----
  const userParams = useMemo(() => extractStructuredParams(message.content), [message.content])
  const userStructured = userParams.length >= 2
  const userLeftover = useMemo(
    () => (userStructured ? stripParamBlocks(message.content, userParams) : ''),
    [userStructured, message.content, userParams],
  )
  const leadingParams = useMemo(() => extractLeadingParams(renderContent), [renderContent])
  const assistantStructured = leadingParams.structured
  const displayContent = assistantStructured ? leadingParams.rest : renderContent

  async function copyText(): Promise<void> {
    try {
      await navigator.clipboard.writeText(message.content)
      toast.success('已复制')
    } catch {
      // clipboard 权限被拒时降级提示
      toast.warning('复制失败，请手动选择文本')
    }
  }

  // 用户消息：右侧软玻璃气泡；结构化输入渲染为 KV 卡片网格，剩余正文兜底展示
  if (!isAssistant) {
    return (
      <motion.div
        className="flex justify-end"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
      >
        <div className="max-w-[82%]">
          {userStructured ? (
            <div className="flex flex-col items-end gap-2">
              <div className="w-full min-w-0">
                <StructuredParams params={userParams} title="输入参数" max={8} />
              </div>
              {userLeftover !== '' && (
                <div className="whitespace-pre-wrap break-words rounded-2xl rounded-br-sm border border-border bg-surface-2/70 px-4 py-2.5 text-[15px] leading-relaxed text-text-1 shadow-card backdrop-blur-sm">
                  {userLeftover}
                </div>
              )}
            </div>
          ) : (
            <div className="whitespace-pre-wrap break-words rounded-2xl rounded-br-sm border border-border bg-surface-2/70 px-4 py-2.5 text-[15px] leading-relaxed text-text-1 shadow-card backdrop-blur-sm">
              {message.content}
            </div>
          )}
        </div>
      </motion.div>
    )
  }

  return (
    <motion.div
      className="group flex gap-3.5"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className="mt-1 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-brand-gradient text-white shadow-glow-brand ring-1 ring-brand-2/25">
        <Sparkles className="h-4 w-4" />
      </div>

      <div className="relative min-w-0 flex-1 pt-0.5">
        {hasThinking && <ThinkingPanel message={message} />}

        {assistantStructured && (
          <div className="mb-2.5">
            <StructuredParams params={leadingParams.params} variant="pills" max={6} />
          </div>
        )}

        {streamingEmpty ? (
          <div role="status" className="flex h-6 items-center gap-1" aria-label="正在思考">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
          </div>
        ) : (
          <div className={cn('markdown-wrap', streaming && 'is-streaming')}>
            <Markdown content={displayContent} streaming={streaming} />
          </div>
        )}

        {/* 生成中状态徽章（替代纯文字状态行） */}
        {streaming && !streamingEmpty && (
          <div role="status" className="mt-2.5 flex items-center gap-1.5">
            <StatusBadge
              tone={thinkingActive ? 'thinking' : 'generating'}
              label={thinkingActive ? '深度思考' : '生成中'}
              pulse
            />
          </div>
        )}

        {message.status === 'error' && (
          <div className="mt-2 flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-[13px] text-destructive">
            <span className="flex-1">{message.errorMessage}</span>
            <button
              type="button"
              onClick={onRetry}
              className="flex items-center gap-1 font-medium hover:underline"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              重试
            </button>
          </div>
        )}

        {/* 收尾后悬停操作：状态徽章 + 复制 / 重新生成 */}
        {message.status === 'done' && (
          <div className="absolute -top-2 right-0 flex items-center gap-0.5 rounded-lg border border-border bg-surface-1 p-0.5 opacity-0 shadow-card transition-opacity duration-150 group-hover:opacity-100">
            <span className="ml-1 mr-0.5">
              <StatusBadge tone="done" label="已生成" />
            </span>
            <button
              type="button"
              title="复制"
              onClick={() => void copyText()}
              className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-text-3 transition-colors hover:bg-surface-hover hover:text-text-1"
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
            {canRegenerate && (
              <button
                type="button"
                title="重新生成"
                onClick={onRetry}
                className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-text-3 transition-colors hover:bg-surface-hover hover:text-text-1"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
    </motion.div>
  )
}

export const MessageBubble = memo(MessageBubbleInner)
