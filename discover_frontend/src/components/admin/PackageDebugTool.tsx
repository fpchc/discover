import { Bug, Loader2, Play } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { errorCategoryLabel } from '@/lib/admin-packages'
import { smokeTestPackageTool } from '@/lib/api'
import { mapHttpError } from '@/lib/errors'
import type { ToolSmokeResult } from '@/types'

interface PackageDebugToolProps {
  packageId: string
}

/**
 * 工具冒烟测试：对当前草稿执行一次真实工具调用，展示成功内容或失败诊断。
 * tool_name 支持短名 / 限定名，arguments 为 JSON 对象字符串。
 */
export function PackageDebugTool({ packageId }: PackageDebugToolProps) {
  const [toolName, setToolName] = useState('')
  const [argsText, setArgsText] = useState('{}')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<ToolSmokeResult | null>(null)

  async function handleRun(): Promise<void> {
    const name = toolName.trim()
    if (name === '') {
      toast.error('请输入工具名')
      return
    }
    let args: Record<string, unknown>
    try {
      const parsed: unknown = JSON.parse(argsText)
      // JSON.parse 运行时边界：收窄为对象参数
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('arguments 必须是 JSON 对象')
      }
      args = parsed as Record<string, unknown>
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'arguments 不是合法 JSON')
      return
    }

    setRunning(true)
    setResult(null)
    try {
      const data = await smokeTestPackageTool(packageId, name, args)
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
        <Bug className="h-4 w-4 text-brand-2" />
        <h2 className="text-[14px] font-semibold text-text-1">工具冒烟测试</h2>
      </header>
      <p className="mt-1 text-[12px] leading-relaxed text-text-3">
        对草稿版本执行一次真实调用；短名有歧义会返回候选，未命中返回 404。
      </p>

      <div className="mt-3 space-y-2.5">
        <Input
          value={toolName}
          onChange={(event) => setToolName(event.target.value)}
          placeholder="工具名，如 score_calculator"
          aria-label="工具名"
        />
        <Textarea
          value={argsText}
          onChange={(event) => setArgsText(event.target.value)}
          placeholder='工具参数 JSON，如 { "query": "储能电池" }'
          className="min-h-24 font-mono text-[12px]"
          aria-label="工具参数 JSON"
        />
        <Button type="button" size="sm" onClick={() => void handleRun()} disabled={running}>
          {running ? <Loader2 className="animate-spin" /> : <Play />}
          运行测试
        </Button>
      </div>

      {result !== null && (
        <div className="mt-3 space-y-2.5 border-t border-border pt-3">
          <div className="flex items-center gap-2">
            <span
              className={
                result.ok
                  ? 'text-[13px] font-medium text-success'
                  : 'text-[13px] font-medium text-destructive'
              }
            >
              {result.ok ? '执行成功' : '执行失败'}
            </span>
            <span className="text-[12px] text-text-3">
              {result.tool_name} · {result.duration_ms}ms
            </span>
          </div>

          {result.content !== '' && (
            <pre className="max-h-60 overflow-auto rounded-lg border border-border bg-surface-2 p-3 text-[12px] leading-relaxed whitespace-pre-wrap text-text-1">
              {result.content}
            </pre>
          )}

          {!result.ok && (
            <div className="space-y-1.5 text-[12px] leading-relaxed">
              <p className="text-text-1">
                <span className="text-text-3">分类：</span>
                {errorCategoryLabel(result.error_category)}
              </p>
              {result.message !== '' && <p className="text-destructive">{result.message}</p>}
              {result.suggestion !== null && (
                <p className="text-text-2">
                  <span className="text-text-3">建议：</span>
                  {result.suggestion}
                </p>
              )}
            </div>
          )}

          {(result.truncated || result.produced_files.length > 0) && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-text-3">
              {result.truncated && <span>输出已截断</span>}
              {result.produced_files.length > 0 && (
                <span>产出文件：{result.produced_files.join('、')}</span>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
