import { Loader2, Plus, RefreshCw, RotateCcw, Search } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { PackageStatusPill } from '@/components/admin/PackageStatusPill'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { formatPackageTime } from '@/lib/admin-packages'
import { createPackageDraft, fetchAdminPackages, rollbackPackage } from '@/lib/api'
import { mapHttpError } from '@/lib/errors'
import type { PackageSummary } from '@/types'

interface PackageListProps {
  onOpen: (packageId: string) => void
}

/**
 * 技能包列表：筛选 / 刷新已有版本，创建草稿，回滚已发布版本。
 * 数据只在本页内存态维护；进入编辑器后返回本列表会重新拉取。
 */
export function PackageList({ onOpen }: PackageListProps) {
  const [appliedAgentId, setAppliedAgentId] = useState('')
  const [filterInput, setFilterInput] = useState('')
  const [list, setList] = useState<PackageSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')
  const [draftAgentId, setDraftAgentId] = useState('')
  const [draftDisplayName, setDraftDisplayName] = useState('')
  const [draftVersion, setDraftVersion] = useState('')
  const [creating, setCreating] = useState(false)
  const [rollbackTarget, setRollbackTarget] = useState<PackageSummary | null>(null)
  const [rollbackVersion, setRollbackVersion] = useState('')
  const [rollingBack, setRollingBack] = useState(false)

  const load = useCallback(async (agentId: string): Promise<void> => {
    setLoading(true)
    setErrorMessage('')
    try {
      const data = await fetchAdminPackages(agentId)
      setList(data)
    } catch (error) {
      setList([])
      setErrorMessage(mapHttpError(error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(appliedAgentId)
  }, [load, appliedAgentId])

  async function handleCreateDraft(): Promise<void> {
    const agentId = draftAgentId.trim()
    const version = draftVersion.trim()
    if (agentId === '') {
      toast.error('请输入 agent_id')
      return
    }
    if (version === '') {
      toast.error('请输入版本号')
      return
    }
    setCreating(true)
    try {
      const detail = await createPackageDraft(agentId, version, draftDisplayName.trim())
      toast.success(`已创建草稿 ${detail.agent_id}@${detail.version}`)
      onOpen(detail.package_id)
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setCreating(false)
    }
  }

  function handleRollbackOpen(target: PackageSummary): void {
    setRollbackTarget(target)
    setRollbackVersion(target.version)
  }

  async function handleRollbackConfirm(): Promise<void> {
    if (rollbackTarget === null || rollbackVersion.trim() === '') return
    setRollingBack(true)
    try {
      await rollbackPackage(rollbackTarget.agent_id, rollbackVersion.trim())
      toast.success(`已回滚 ${rollbackTarget.agent_id} 到 ${rollbackVersion.trim()}`)
      setRollbackTarget(null)
      void load(appliedAgentId)
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setRollingBack(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-[960px] px-4 pb-10 pt-3 sm:px-6">
      <section className="rounded-xl border border-border bg-surface-1 p-4 shadow-card">
        <h2 className="text-[14px] font-semibold text-text-1">创建草稿</h2>
        <p className="mt-1 text-[12px] leading-relaxed text-text-3">
          使用标准包模板创建独立的 AGENT.md、示例技能、参考文档和输出模板。
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_160px_auto]">
          <Input
            value={draftAgentId}
            onChange={(event) => setDraftAgentId(event.target.value)}
            placeholder="agent_id，如 sales-research"
            aria-label="创建草稿 agent_id"
          />
          <Input
            value={draftDisplayName}
            onChange={(event) => setDraftDisplayName(event.target.value)}
            placeholder="显示名称，可选"
            aria-label="创建草稿显示名称"
          />
          <Input
            value={draftVersion}
            onChange={(event) => setDraftVersion(event.target.value)}
            placeholder="版本号，如 1.7.0"
            aria-label="创建草稿版本号"
          />
          <Button type="button" onClick={() => void handleCreateDraft()} disabled={creating}>
            {creating ? <Loader2 className="animate-spin" /> : <Plus />}
            创建草稿
          </Button>
        </div>
      </section>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <div className="flex flex-1 items-center gap-2">
          <Input
            value={filterInput}
            onChange={(event) => setFilterInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') setAppliedAgentId(filterInput.trim())
            }}
            placeholder="按 agent_id 筛选（留空返回全部）"
            aria-label="筛选 agent_id"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            title="筛选"
            onClick={() => setAppliedAgentId(filterInput.trim())}
          >
            <Search />
          </Button>
        </div>
        <Button type="button" variant="outline" onClick={() => void load(appliedAgentId)}>
          <RefreshCw />
          刷新
        </Button>
      </div>

      {loading ? (
        <div className="mt-4 space-y-2">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : errorMessage !== '' ? (
        <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-[13px] text-destructive">
          {errorMessage}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="ml-3"
            onClick={() => void load(appliedAgentId)}
          >
            重试
          </Button>
        </div>
      ) : list.length === 0 ? (
        <div className="mt-4 rounded-xl border border-border bg-surface-1 p-6 text-center text-[13px] text-text-3">
          暂无技能包，请先创建草稿。
        </div>
      ) : (
        <ul className="mt-4 space-y-2">
          {list.map((item) => (
            <li
              key={item.package_id}
              className="rounded-xl border border-border bg-surface-1 p-3 shadow-card"
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <PackageStatusPill status={item.status} />
                    <span className="text-[14px] font-semibold text-text-1">
                      {item.agent_id}@{item.version}
                    </span>
                    {item.enabled && (
                      <span className="text-[11px] font-medium text-success">当前生效</span>
                    )}
                  </div>
                  <p className="mt-1 text-[12px] text-text-3">
                    更新于 {formatPackageTime(item.updated_at)}
                  </p>
                </div>
                <div className="flex flex-shrink-0 items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onOpen(item.package_id)}
                  >
                    打开
                  </Button>
                  {item.status === 'published' && !item.enabled && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => handleRollbackOpen(item)}
                    >
                      <RotateCcw />
                      回滚
                    </Button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <AlertDialog
        open={rollbackTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRollbackTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>回滚技能包</AlertDialogTitle>
            <AlertDialogDescription>
              {rollbackTarget !== null
                ? `将 ${rollbackTarget.agent_id} 回滚到指定已发布版本，回滚后立即生效。`
                : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Input
            value={rollbackVersion}
            onChange={(event) => setRollbackVersion(event.target.value)}
            placeholder="已发布版本号，如 1.6.0"
            aria-label="回滚目标版本号"
          />
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <Button variant="outline">取消</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                type="button"
                onClick={() => void handleRollbackConfirm()}
                disabled={rollingBack}
              >
                {rollingBack ? <Loader2 className="animate-spin" /> : null}
                确认回滚
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
