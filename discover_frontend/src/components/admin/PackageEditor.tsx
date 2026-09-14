// pragma: 简化 — 编排页：技能包编辑器集中编排文件列表 / 保存 / 校验 / 发布 / 调试面板。
import { FilePlus2, Loader2, Rocket, Save, ShieldCheck, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { PackageDebugPreview } from '@/components/admin/PackageDebugPreview'
import { PackageDebugTool } from '@/components/admin/PackageDebugTool'
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
import { cn } from '@/lib/utils'
import type { PackageDetail, PackageFile, ValidateResult } from '@/types'

interface PackageEditorProps {
  packageId: string
}

function upsertFile(files: PackageFile[], next: PackageFile): PackageFile[] {
  const index = files.findIndex((file) => file.path === next.path)
  if (index === -1) return [...files, next]
  return files.map((file, current) => (current === index ? next : file))
}

function removeFile(files: PackageFile[], path: string): PackageFile[] {
  return files.filter((file) => file.path !== path)
}

/** 技能包编辑器：只编辑 AGENT.md / SKILL.md / references / templates，scripts、schemas 由代码发布。 */
export function PackageEditor({ packageId }: PackageEditorProps) {
  const [detail, setDetail] = useState<PackageDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [selectedPath, setSelectedPath] = useState('')
  const [draftContent, setDraftContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [newPath, setNewPath] = useState('')
  const [creatingFile, setCreatingFile] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [validateResult, setValidateResult] = useState<ValidateResult | null>(null)
  const [validating, setValidating] = useState(false)
  const [publishOpen, setPublishOpen] = useState(false)
  const [publishing, setPublishing] = useState(false)

  const loadDetail = useCallback(async (): Promise<void> => {
    setLoading(true)
    setLoadError('')
    try {
      const data = await fetchPackageDetail(packageId)
      setDetail(data)
      const firstPath = data.files[0]?.path ?? ''
      setSelectedPath(firstPath)
      setDraftContent(data.files[0]?.content ?? '')
      setDirty(false)
      setValidateResult(null)
    } catch (error) {
      setLoadError(mapHttpError(error).message)
    } finally {
      setLoading(false)
    }
  }, [packageId])

  useEffect(() => {
    void loadDetail()
  }, [loadDetail])

  function selectFile(path: string): void {
    const file = detail?.files.find((item) => item.path === path)
    setSelectedPath(path)
    setDraftContent(file?.content ?? '')
    setDirty(false)
    setValidateResult(null)
  }

  async function handleSave(): Promise<void> {
    if (selectedPath === '') {
      toast.error('请先选择文件')
      return
    }
    setSaving(true)
    try {
      const saved = await savePackageFile(packageId, selectedPath, draftContent)
      setDetail((previous) =>
        previous === null ? previous : { ...previous, files: upsertFile(previous.files, saved) },
      )
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
      setDetail((previous) =>
        previous === null ? previous : { ...previous, files: upsertFile(previous.files, saved) },
      )
      setSelectedPath(saved.path)
      setDraftContent('')
      setNewPath('')
      setDirty(false)
      toast.success('文件已创建')
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setCreatingFile(false)
    }
  }

  async function handleDeleteConfirm(): Promise<void> {
    if (deleteTarget === null) return
    setDeleting(true)
    try {
      await deletePackageFile(packageId, deleteTarget)
      const nextFiles = detail?.files.filter((file) => file.path !== deleteTarget) ?? []
      setDetail((previous) =>
        previous === null
          ? previous
          : { ...previous, files: removeFile(previous.files, deleteTarget) },
      )
      if (selectedPath === deleteTarget) {
        const next = nextFiles[0]
        setSelectedPath(next?.path ?? '')
        setDraftContent(next?.content ?? '')
        setDirty(false)
      }
      setDeleteTarget(null)
      toast.success('文件已删除')
    } catch (error) {
      toast.error(mapHttpError(error).message)
    } finally {
      setDeleting(false)
    }
  }

  async function handleValidate(): Promise<void> {
    setValidating(true)
    setValidateResult(null)
    try {
      const result = await validatePackage(packageId)
      setValidateResult(result)
      if (result.ok) {
        toast.success('校验通过')
      } else {
        toast.error(`校验失败，共 ${result.errors.length} 项`)
      }
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
      <div className="mx-auto w-full max-w-[1100px] space-y-3 px-4 pb-10 pt-3 sm:px-6">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-[420px] w-full" />
      </div>
    )
  }

  if (loadError !== '') {
    return (
      <div className="mx-auto w-full max-w-[1100px] px-4 pb-10 pt-3 sm:px-6">
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
    <div className="mx-auto w-full max-w-[1100px] px-4 pb-10 pt-3 sm:px-6">
      <section className="rounded-xl border border-border bg-surface-1 p-4 shadow-card">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <PackageStatusPill status={detail.status} />
            <h2 className="text-[16px] font-semibold text-text-1">
              {detail.agent_id}@{detail.version}
            </h2>
            {detail.enabled && (
              <span className="text-[11px] font-medium text-success">当前生效</span>
            )}
          </div>
          <div className="text-[12px] text-text-3">
            更新于 {formatPackageTime(detail.updated_at)}
            {detail.published_at !== null && (
              <> · 发布于 {formatPackageTime(detail.published_at)}</>
            )}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <Button
            type="button"
            size="sm"
            onClick={() => void handleSave()}
            disabled={!dirty || selectedPath === '' || saving}
          >
            {saving ? <Loader2 className="animate-spin" /> : <Save />}
            保存
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void handleValidate()}
            disabled={validating}
          >
            {validating ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
            校验
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => setPublishOpen(true)}
            disabled={publishing || detail.status !== 'draft'}
            title={detail.status !== 'draft' ? '仅草稿可发布' : undefined}
          >
            <Rocket />
            发布
          </Button>
        </div>

        {validateResult !== null && !validateResult.ok && (
          <div className="mt-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3">
            <p className="text-[13px] font-medium text-destructive">
              校验失败（{validateResult.errors.length} 项）
            </p>
            <ul className="mt-1.5 list-inside list-disc space-y-1 text-[12px] leading-relaxed text-text-1">
              {validateResult.errors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <div className="mt-4 grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="rounded-xl border border-border bg-surface-1 p-3 shadow-card">
          <div className="flex items-center justify-between">
            <h3 className="text-[13px] font-semibold text-text-1">可编辑文件</h3>
            <span className="text-[11px] text-text-3">{detail.files.length} 个</span>
          </div>
          <div className="mt-2 flex gap-1.5">
            <Input
              value={newPath}
              onChange={(event) => setNewPath(event.target.value)}
              placeholder="references/xx.md"
              aria-label="新文件路径"
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              title="新建文件"
              onClick={() => void handleCreateFile()}
              disabled={creatingFile}
            >
              {creatingFile ? <Loader2 className="animate-spin" /> : <FilePlus2 />}
            </Button>
          </div>
          <ul className="mt-2 max-h-[520px] space-y-0.5 overflow-y-auto">
            {detail.files.map((file) => (
              <li key={file.path}>
                <button
                  type="button"
                  onClick={() => selectFile(file.path)}
                  className={cn(
                    'w-full cursor-pointer truncate rounded-lg px-2.5 py-2 text-left text-[12px] leading-relaxed transition-colors',
                    selectedPath === file.path
                      ? 'sidebar-active sidebar-active--bar font-medium text-text-1'
                      : 'text-text-2 hover:bg-surface-hover hover:text-text-1',
                  )}
                  title={file.path}
                >
                  {file.path}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="min-w-0 rounded-xl border border-border bg-surface-1 p-3 shadow-card">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="min-w-0 truncate text-[13px] font-semibold text-text-1">
              {selectedPath === '' ? '未选择文件' : selectedPath}
            </h3>
            {selectedPath !== '' && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setDeleteTarget(selectedPath)}
              >
                <Trash2 />
                删除
              </Button>
            )}
          </div>
          {selectedPath === '' ? (
            <div className="flex h-[400px] items-center justify-center rounded-lg border border-border text-[13px] text-text-3">
              请从左侧选择文件，或新建一个文件。
            </div>
          ) : (
            <Textarea
              value={draftContent}
              onChange={(event) => {
                setDraftContent(event.target.value)
                setDirty(true)
              }}
              spellCheck={false}
              className="min-h-[400px] resize-y font-mono text-[12px] leading-relaxed"
              aria-label="文件内容"
            />
          )}
        </section>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <PackageDebugTool packageId={packageId} />
        <PackageDebugPreview packageId={packageId} />
      </div>

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
              {deleteTarget !== null ? `确定删除「${deleteTarget}」吗？该操作不可恢复。` : ''}
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
