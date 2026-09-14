import { Loader2, Send } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Markdown } from '@/components/Markdown'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { previewPackageDraft } from '@/lib/api'
import { mapHttpError } from '@/lib/errors'
import type { PreviewResult } from '@/types'

interface PackageDebugPreviewProps {
  packageId: string
}

const DEFAULT_INPUT = '帮我在深圳找做储能电池的潜在客户'

/**
 * 草稿预览对话：对草稿版本跑一次真实对话（真实 LLM + 真实 MCP/数据源）。
 * 返回 answer / thinking / events；耗时较长，前端使用 ADMIN_DEBUG_TIMEOUT_MS 独立超时。
 */
export function PackageDebugPreview({ packageId }: PackageDebugPreviewProps) {
  const [userInput, setUserInput] = useState(DEFAULT_INPUT)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<PreviewResult | null>(null)

  async function handleRun(): Promise<void> {
    const input = userInput.trim()
    if (input === '') {
      toast.error('请输入预览对话内容')
      return
    }
    setRunning(true)
    setResult(null)
    try {
      const data = await previewPackageDraft(packageId, input)
      setResult(data)
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <section className="rounded-xl border border-border bg-surface-1 p-4 shadow-card">
      <header className="flex items-center gap-2">
        <Send className="h-4 w-4 text-brand-2" />
        <h2 className="text-[14px] font-semibold text-text-1">草稿预览对话</h2>
      </header>
      <p className="mt-1 text-[12px] leading-relaxed text-text-3">
        使用草稿版本运行真实对话；会调用真实 LLM 与数据源，可能产生计费，耗时较长。
      </p>

      <div className="mt-3 space-y-2.5">
        <Textarea
          value={userInput}
          onChange={(event) => setUserInput(event.target.value)}
          className="min-h-20"
          aria-label="预览对话输入"
        />
        <Button type="button" size="sm" onClick={() => void handleRun()} disabled={running}>
          {running ? <Loader2 className="animate-spin" /> : <Send />}
          运行预览
        </Button>
      </div>

      {result !== null && (
        <div className="mt-3 space-y-3 border-t border-border pt-3">
          <p className="text-[12px] text-text-3">
            outcome_type：{result.outcome_type ?? '无'} · 事件 {result.events.length} 条
          </p>

          <div>
            <h3 className="mb-1.5 text-[13px] font-medium text-text-1">最终正文</h3>
            <div className="rounded-lg border border-border bg-surface-2 p-3">
              <Markdown content={result.answer} />
            </div>
          </div>

          {result.thinking !== '' && (
            <div>
              <h3 className="mb-1.5 text-[13px] font-medium text-text-1">思考过程</h3>
              <pre className="max-h-60 overflow-auto rounded-lg border border-border bg-surface-2 p-3 text-[12px] leading-relaxed whitespace-pre-wrap text-text-2">
                {result.thinking}
              </pre>
            </div>
          )}

          {result.events.length > 0 && (
            <details className="rounded-lg border border-border bg-surface-2">
              <summary className="cursor-pointer select-none px-3 py-2 text-[12px] font-medium text-text-1">
                完整执行 trace（{result.events.length} 条）
              </summary>
              <div className="max-h-96 overflow-auto border-t border-border p-3">
                <ol className="space-y-2">
                  {result.events.map((event) => (
                    <li key={event.seq} className="text-[12px] leading-relaxed">
                      <span className="font-medium text-brand-2">
                        #{event.seq} {event.event_type}
                      </span>
                      <pre className="mt-1 overflow-x-auto rounded bg-black/5 p-2 text-[11px] whitespace-pre-wrap dark:bg-white/5">
                        {JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </li>
                  ))}
                </ol>
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  )
}
