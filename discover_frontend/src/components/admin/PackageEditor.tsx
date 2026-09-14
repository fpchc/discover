// pragma: 简化 — 编排页：技能包编辑器集中编排文件树 / 保存 / 校验 / 发布 / 调试面板。
import {
  FilePlus2,
  FileText,
  Loader2,
  Package,
  RefreshCw,
  Rocket,
  Save,
  ShieldCheck,
  Trash2,
  Wrench,
} from 'lucide-react'
import { type ReactElement, useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { PackageDebugPreview } from '@/components/admin/PackageDebugPreview'
import { PackageDebugTool } from '@/components/admin/PackageDebugTool'
import { PackageFileTree } from '@/components/admin/PackageFileTree'
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
import { Textarea } from '@/components/ui/textarea'
import { formatPackageTime } from '@/lib/admin-packages'
import {
  deletePackageFile,
  fetchPackageDetail,
  publishPackage,
  savePackageFile,
  validatePackage,
} from '@/lib/api'
import { mapHttpError } from '@/lib/errors'
import {
  countPackageFiles,
  packageEntriesFromDetail,
  removePackageEntryAndEmptyDirectories,
} from '@/lib/package-tree'
import { cn } from '@/lib/utils'
import type { PackageDetail, PackageEntry, ValidateResult } from '@/types'

interface PackageEditorProps {
  packageId: string
}

type PackageEditorTab = 'files' | 'debug'

function updatePackageFileContent(
  detail: PackageDetail,
  path: string,
  content: string,
): PackageDetail {
  return {
    ...detail,
    entries: detail.entries?.map((entry) => (entry.path === path ? { ...entry, content } : entry)),
    files: detail.files?.map((file) => (file.path === path ? { ...file, content } : file)),
  }
}

function removePackageFile(detail: PackageDetail, path: string): PackageDetail {
  return {
    ...detail,
    entries:
      detail.entries === undefined
        ? undefined
        : removePackageEntryAndEmptyDirectories(detail.entries, path),
    files: detail.files?.filter((file) => file.path !== path),
  }
}

function findEntryByPath(entries: PackageEntry[], path: string): PackageEntry | null {
  if (path === '') return null
  return entries.find((entry) => entry.entry_type === 'file' && entry.path === path) ?? null
}

function findDefaultEntry(entries: PackageEntry[]): PackageEntry | null {
  const agentEntry = entries.find(
    (entry) => entry.entry_type === 'file' && entry.path === 'AGENT.md',
  )
  return agentEntry ?? entries.find((entry) => entry.entry_type === 'file') ?? null
}

function expandEntryAncestors(
  entries: PackageEntry[],
  selected: PackageEntry | null,
  collapsed: Set<number>,
): Set<number> {
  const next = new Set(collapsed)
  const visited = new Set<number>()
  let parentId = selected?.parent_id ?? null
  while (parentId !== null && !visited.has(parentId)) {
    visited.add(parentId)
    next.delete(parentId)
    parentId = entries.find((entry) => entry.entry_id === parentId)?.parent_id ?? null
  }
  return next
}

function findNextFilePath(entries: PackageEntry[], deletedPath: string): string {
  const files = entries.filter((entry) => entry.entry_type === 'file')
  const deletedIndex = files.findIndex((entry) => entry.path === deletedPath)
  const remaining = files.filter((entry) => entry.path !== deletedPath)
  if (remaining.length === 0) return ''
  if (deletedIndex < 0) return remaining[0].path
  return (remaining[deletedIndex] ?? remaining[deletedIndex - 1] ?? remaining[0]).path
}

/** 技能包编辑器：文件树与调试工具分栏，稳定 entry_id 负责选择和折叠。 */
export function PackageEditor({ packageId }: PackageEditorProps): ReactElement | null {
  const [detail, setDetail] = useState<PackageDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [activeTab, setActiveTab] = useState<PackageEditorTab>('files')
  const [selectedEntryId, setSelectedEntryId] = useState<number | null>(null)
  const [draftContent, setDraftContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [creatingFile, setCreatingFile] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<PackageEntry | null>(null)
  const [pendingEntryId, setPendingEntryId] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [validateResult, setValidateResult] = useState<ValidateResult | null>(null)
  const [validating, setValidating] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [collapsedEntryIds, setCollapsedEntryIds] = useState<Set<number>>(new Set())

  const entries = useMemo(
    (): PackageEntry[] => (detail === null ? [] : packageEntriesFromDetail(detail)),
    [detail],
  )
  const fileCount = useMemo((): number => countPackageFiles(entries), [entries])
  const selectedEntry = useMemo(
    (): PackageEntry | null =>
      entries.find((entry) => entry.entry_type === 'file' && entry.entry_id === selectedEntryId) ??
      null,
    [entries, selectedEntryId],
  )
  const pendingEntry = useMemo(
    (): PackageEntry | null =>
      entries.find((entry) => entry.entry_type === 'file' && entry.entry_id === pendingEntryId) ??
      null,
    [entries, pendingEntryId],
  )

  const applyDetail = useCallback((data: PackageDetail, preferredPath = ''): void => {
    const nextEntries = packageEntriesFromDetail(data)
    const selected = findEntryByPath(nextEntries, preferredPath) ?? findDefaultEntry(nextEntries)
    setDetail(data)
    setSelectedEntryId(selected?.entry_id ?? null)
    setDraftContent(selected?.content ?? '')
    setDirty(false)
    setValidateResult(null)
    setCollapsedEntryIds((previous) => expandEntryAncestors(nextEntries, selected, previous))
  }, [])

  const loadDetail = useCallback(async (): Promise<void> => {
    setLoading(true)
    setLoadError('')
    try {
      const data = await fetchPackageDetail(packageId)
      applyDetail(data)
    } catch (error) {
      setLoadError(mapHttpError(error).message)
    } finally {
      setLoading(false)
    }
  }, [applyDetail, packageId])

  useEffect((): void => {
    void loadDetail()
  }, [loadDetail])

  function openEntry(entry: PackageEntry): void {
    setSelectedEntryId(entry.entry_id)
    setDraftContent(entry.content ?? '')
    setDirty(false)
    setValidateResult(null)
  }

  function selectEntry(entryId: number): void {
    const entry = entries.find((item) => item.entry_type === 'file' && item.entry_id === entryId)
    if (entry === undefined || entry.entry_id === selectedEntryId) return
    if (dirty) {
      setPendingEntryId(entryId)
      return
    }
    openEntry(entry)
  }

  function confirmDiscardSwitch(): void {
    if (pendingEntry === null) return
    openEntry(pendingEntry)
    setPendingEntryId(null)
  }

  async function handleSave(): Promise<void> {
    if (selectedEntry === null) {
      toast.error('请先选择文件')
      return
    }
    setSaving(true)
    try {
      const saved = await savePackageFile(packageId, selectedEntry.path, draftContent)
      setDetail((previous) =>
        previous === null
          ? previous
          : updatePackageFileContent(previous, saved.path, saved.content),
      )
      setDraftContent(saved.content)
      setDirty(false)
      toast.success('文件已保存')
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setSaving(false)
    }
  }

  async function handleCreateFile(): Promise<void> {
    const path = newPath.trim()
    if (path === '') {
      toast.error('请输入文件相对路径')
      return
    }
    setCreatingFile(true)
    try {
      const saved = await savePackageFile(packageId, path, '')
      setNewPath('')
      toast.success('文件已创建')
      try {
        const data = await fetchPackageDetail(packageId)
        applyDetail(data, saved.path)
      } catch (refreshError) {
        toast.error(`文件已创建，但目录刷新失败：${mapHttpError(refreshError).message}`)
      }
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setCreatingFile(false)
    }
  }

  async function handleDeleteConfirm(): Promise<void> {
    if (deleteTarget === null) return
    const target = deleteTarget
    const nextPath = findNextFilePath(entries, target.path)
    setDeleting(true)
    try {
      await deletePackageFile(packageId, target.path)
      if (detail !== null) applyDetail(removePackageFile(detail, target.path), nextPath)
      setDeleteTarget(null)
      toast.success('文件已删除')
      try {
        const data = await fetchPackageDetail(packageId)
        applyDetail(data, nextPath)
      } catch (refreshError) {
        toast.error(`文件已删除，但目录刷新失败：${mapHttpError(refreshError).message}`)
      }
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setDeleting(false)
    }
  }

  async function handleRefresh(): Promise<void> {
    setRefreshing(true)
    try {
      const data = await fetchPackageDetail(packageId)
      applyDetail(data, selectedEntry?.path ?? '')
      toast.success('技能包已刷新')
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setRefreshing(false)
    }
  }

  async function handleValidate(): Promise<void> {
    setValidating(true)
    setValidateResult(null)
    try {
      const result = await validatePackage(packageId)
      setValidateResult(result)
      if (result.ok) toast.success('校验通过')
      else toast.error(`校验失败，共 ${result.errors.length} 项`)
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setValidating(false)
    }
  }

  async function handlePublishConfirm(): Promise<void> {
    setPublishing(true)
    try {
      await publishPackage(packageId)
      setDetail((previous) =>
        previous === null
          ? previous
          : {
              ...previous,
              status: 'published',
              enabled: true,
              published_at: new Date().toISOString(),
            },
      )
      setPublishOpen(false)
      toast.success('发布成功，已切换为当前生效版本')
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setPublishing(false)
    }
  }

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-[1440px] space-y-3 px-4 pb-10 pt-3 sm:px-6">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-[560px] w-full" />
      </div>
    )
  }

  if (loadError !== '') {
    return (
      <div className="mx-auto w-full max-w-[1440px] px-4 pb-10 pt-3 sm:px-6">
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-[13px] text-destructive">
          {loadError}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="ml-3"
            onClick={() => void loadDetail()}
          >
            重试
          </Button>
        </div>
      </div>
    )
  }

  if (detail === null) return null

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-4 px-4 pb-12 pt-3 sm:px-6">
      <section className="overflow-hidden rounded-2xl border border-border bg-surface-1 shadow-card">
        <div className="flex flex-col gap-4 p-4 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex size-10 flex-shrink-0 items-center justify-center rounded-xl bg-brand-2/10 text-brand-2">
              <Package className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <PackageStatusPill status={detail.status} />
                <h2 className="truncate text-[16px] font-semibold text-text-1">
                  {detail.agent_id}@{detail.version}
                </h2>
                {detail.enabled && (
                  <span className="text-[11px] font-medium text-success">当前生效</span>
                )}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-text-3">
                <span>更新于 {formatPackageTime(detail.updated_at)}</span>
                {detail.published_at !== null && (
                  <span>发布于 {formatPackageTime(detail.published_at)}</span>
                )}
                <span>{fileCount} 个文件</span>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {dirty && (
              <span className="rounded-full bg-amber-500/10 px-2.5 py-1 text-[11px] font-medium text-amber-700 dark:text-amber-400">
                有未保存修改
              </span>
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void handleRefresh()}
              disabled={refreshing || dirty}
              title={dirty ? '请先保存当前文件' : '刷新技能包'}
            >
              {refreshing ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              刷新
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void handleValidate()}
              disabled={validating || dirty}
              title={dirty ? '请先保存当前文件' : '校验已保存内容'}
            >
              {validating ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
              校验
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => setPublishOpen(true)}
              disabled={publishing || dirty || detail.status !== 'draft'}
              title={
                detail.status !== 'draft' ? '仅草稿可发布' : dirty ? '请先保存当前文件' : undefined
              }
            >
              <Rocket />
              发布
            </Button>
          </div>
        </div>

        <div className="flex gap-1 border-t border-border bg-surface-2/40 px-2 py-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className={cn(activeTab === 'files' && 'bg-surface-1 text-text-1 shadow-sm')}
            onClick={() => setActiveTab('files')}
            aria-pressed={activeTab === 'files'}
          >
            <FileText />
            文件编辑
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className={cn(activeTab === 'debug' && 'bg-surface-1 text-text-1 shadow-sm')}
            onClick={() => setActiveTab('debug')}
            aria-pressed={activeTab === 'debug'}
          >
            <Wrench />
            运行调试
          </Button>
        </div>
      </section>

      {activeTab === 'files' ? (
        <div className="grid min-h-0 gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="flex h-[560px] min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-surface-1 shadow-card lg:h-[calc(100vh-270px)] lg:min-h-[560px]">
            <header className="flex items-center justify-between gap-3 border-b border-border px-3.5 py-3">
              <div>
                <h3 className="text-[13px] font-semibold text-text-1">包文件</h3>
                <p className="mt-0.5 text-[11px] text-text-3">目录与可编辑文件</p>
              </div>
              <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-text-3">
                {fileCount} 个文件
              </span>
            </header>

            <div className="border-b border-border p-3">
              <div className="flex gap-1.5">
                <Input
                  value={newPath}
                  onChange={(event) => setNewPath(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !dirty) void handleCreateFile()
                  }}
                  placeholder="client-finder/references/new.md"
                  aria-label="新文件路径"
                  className="h-8 text-[12px]"
                  disabled={dirty}
                  title={dirty ? '请先保存当前文件' : '输入文件相对路径'}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  title={dirty ? '请先保存当前文件' : '按路径新建文件'}
                  onClick={() => void handleCreateFile()}
                  disabled={creatingFile || dirty}
                >
                  {creatingFile ? <Loader2 className="animate-spin" /> : <FilePlus2 />}
                </Button>
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-text-3">
                {dirty ? '当前文件尚未保存，保存后可继续新建。' : '缺失的父目录会由后端自动创建。'}
              </p>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              <PackageFileTree
                entries={entries}
                selectedEntryId={selectedEntryId}
                collapsedEntryIds={collapsedEntryIds}
                onToggle={(entryId) =>
                  setCollapsedEntryIds((previous) => {
                    const next = new Set(previous)
                    if (next.has(entryId)) next.delete(entryId)
                    else next.add(entryId)
                    return next
                  })
                }
                onSelect={selectEntry}
              />
            </div>
          </aside>

          <section className="flex h-[560px] min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-surface-1 shadow-card lg:h-[calc(100vh-270px)] lg:min-h-[560px]">
            <header className="flex min-h-[64px] items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <div className="flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-surface-2 text-text-3">
                  <FileText className="size-4" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate text-[13px] font-semibold text-text-1">
                      {selectedEntry?.name ?? '未选择文件'}
                    </h3>
                    {dirty && (
                      <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400">
                        未保存
                      </span>
                    )}
                  </div>
                  <p className="truncate text-[11px] text-text-3" title={selectedEntry?.path ?? ''}>
                    {selectedEntry?.path ?? '从左侧目录选择一个文件开始编辑'}
                  </p>
                </div>
              </div>

              <div className="flex flex-shrink-0 items-center gap-1.5">
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void handleSave()}
                  disabled={!dirty || selectedEntry === null || saving}
                >
                  {saving ? <Loader2 className="animate-spin" /> : <Save />}
                  保存
                </Button>
                {selectedEntry !== null && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => setDeleteTarget(selectedEntry)}
                  >
                    <Trash2 />
                    <span className="hidden sm:inline">删除</span>
                  </Button>
                )}
              </div>
            </header>

            {selectedEntry === null ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                <div className="flex size-12 items-center justify-center rounded-2xl bg-surface-2 text-text-3">
                  <FileText className="size-6" />
                </div>
                <div>
                  <p className="text-[13px] font-medium text-text-1">选择文件开始编辑</p>
                  <p className="mt-1 text-[12px] text-text-3">也可以在上方输入完整路径新建文件。</p>
                </div>
              </div>
            ) : (
              <Textarea
                value={draftContent}
                onChange={(event) => {
                  setDraftContent(event.target.value)
                  setDirty(true)
                }}
                spellCheck={false}
                className="min-h-0 flex-1 resize-none rounded-none border-0 bg-transparent p-4 font-mono text-[12px] leading-6 shadow-none focus-visible:border-0 focus-visible:ring-0"
                aria-label="文件内容"
              />
            )}
          </section>
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          <PackageDebugTool packageId={packageId} />
          <PackageDebugPreview packageId={packageId} />
        </div>
      )}

      {validateResult !== null && !validateResult.ok && (
        <section className="rounded-xl border border-destructive/30 bg-destructive/10 p-4">
          <p className="text-[13px] font-medium text-destructive">
            校验失败（{validateResult.errors.length} 项）
          </p>
          <ul className="mt-2 list-inside list-disc space-y-1 text-[12px] leading-relaxed text-text-1">
            {validateResult.errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        </section>
      )}

      <AlertDialog
        open={pendingEntryId !== null}
        onOpenChange={(open) => {
          if (!open) setPendingEntryId(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>放弃未保存修改？</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingEntry !== null
                ? `切换到「${pendingEntry.name}」后，当前文件的未保存内容将丢失。`
                : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <Button variant="outline">继续编辑</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button type="button" variant="destructive" onClick={confirmDiscardSwitch}>
                放弃修改
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>删除文件</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget !== null
                ? `确定删除「${deleteTarget.path}」吗？删除后空目录会自动清理。${
                    dirty ? ' 当前文件还有未保存修改。' : ''
                  }`
                : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <Button variant="outline">取消</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                type="button"
                variant="destructive"
                onClick={() => void handleDeleteConfirm()}
                disabled={deleting}
              >
                {deleting ? <Loader2 className="animate-spin" /> : null}
                删除
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={publishOpen}
        onOpenChange={(open) => {
          if (!open) setPublishOpen(false)
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>发布技能包</AlertDialogTitle>
            <AlertDialogDescription>
              {validateResult !== null && !validateResult.ok
                ? '当前校验未通过，发布可能被服务端拒绝。确定仍要发布吗？'
                : '发布后会自动停用该 agent 的其他已发布版本，并立即生效。'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <Button variant="outline">取消</Button>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <Button
                type="button"
                onClick={() => void handlePublishConfirm()}
                disabled={publishing}
              >
                {publishing ? <Loader2 className="animate-spin" /> : null}
                确认发布
              </Button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
