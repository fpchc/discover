import { ChevronRight, CircleAlert, FileText, Folder, FolderOpen, FolderTree } from 'lucide-react'
import { type ReactElement, useMemo } from 'react'
import {
  buildPackageTree,
  type PackageTreeBuildResult,
  type PackageTreeNode,
} from '@/lib/package-tree'
import { cn } from '@/lib/utils'
import type { PackageEntry } from '@/types'

interface PackageFileTreeProps {
  entries: PackageEntry[]
  selectedEntryId: number | null
  collapsedEntryIds: Set<number>
  onToggle: (entryId: number) => void
  onSelect: (entryId: number) => void
}

interface PackageTreeNavigation {
  selectedEntryId: number | null
  collapsedEntryIds: Set<number>
  onToggle: (entryId: number) => void
  onSelect: (entryId: number) => void
}

interface FileTreeNodesProps {
  nodes: PackageTreeNode[]
  depth: number
  navigation: PackageTreeNavigation
}

function FileTreeNodes({ nodes, depth, navigation }: FileTreeNodesProps): ReactElement {
  return (
    <ul className="space-y-0.5">
      {nodes.map((node) => {
        const { entry } = node
        const paddingLeft = 8 + depth * 16

        if (node.kind === 'directory') {
          const collapsed = navigation.collapsedEntryIds.has(entry.entry_id)
          return (
            <li key={entry.entry_id}>
              <button
                type="button"
                onClick={() => navigation.onToggle(entry.entry_id)}
                className="flex w-full cursor-pointer items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left text-[12px] font-medium text-text-2 transition-colors hover:bg-surface-hover hover:text-text-1"
                style={{ paddingLeft }}
                aria-expanded={!collapsed}
                title={entry.path}
              >
                <ChevronRight
                  className={cn(
                    'size-3.5 flex-shrink-0 text-text-3 transition-transform',
                    !collapsed && 'rotate-90',
                  )}
                />
                {collapsed ? (
                  <Folder className="size-3.5 flex-shrink-0 text-brand-2" />
                ) : (
                  <FolderOpen className="size-3.5 flex-shrink-0 text-brand-2" />
                )}
                <span className="truncate">{entry.name}</span>
              </button>
              {!collapsed && (
                <FileTreeNodes nodes={node.children} depth={depth + 1} navigation={navigation} />
              )}
            </li>
          )
        }

        const selected = navigation.selectedEntryId === entry.entry_id
        return (
          <li key={entry.entry_id}>
            <button
              type="button"
              onClick={() => navigation.onSelect(entry.entry_id)}
              className={cn(
                'flex w-full cursor-pointer items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left text-[12px] leading-relaxed transition-colors',
                selected
                  ? 'sidebar-active sidebar-active--bar font-medium text-text-1'
                  : 'text-text-2 hover:bg-surface-hover hover:text-text-1',
              )}
              style={{ paddingLeft }}
              title={entry.path}
              aria-current={selected ? 'page' : undefined}
            >
              <FileText className="size-3.5 flex-shrink-0 text-text-3" />
              <span className="truncate">{entry.name}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function TreeOrphanWarning({ count }: { count: number }): ReactElement | null {
  if (count === 0) return null
  return (
    <div className="mx-1 mb-2 flex gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-2.5 py-2 text-[11px] leading-relaxed text-destructive">
      <CircleAlert className="mt-0.5 size-3.5 flex-shrink-0" />
      <span>有 {count} 个节点缺少有效父目录，已停止展示，请刷新或检查包结构。</span>
    </div>
  )
}

export function PackageFileTree({
  entries,
  selectedEntryId,
  collapsedEntryIds,
  onToggle,
  onSelect,
}: PackageFileTreeProps): ReactElement {
  const tree: PackageTreeBuildResult = useMemo(() => buildPackageTree(entries), [entries])
  const navigation: PackageTreeNavigation = {
    selectedEntryId,
    collapsedEntryIds,
    onToggle,
    onSelect,
  }

  if (tree.nodes.length === 0) {
    return (
      <div className="flex min-h-40 flex-col items-center justify-center gap-2 px-4 text-center text-text-3">
        <FolderTree className="size-7" />
        <p className="text-[12px]">还没有文件，右侧输入路径后创建。</p>
      </div>
    )
  }

  return (
    <div>
      <TreeOrphanWarning count={tree.orphanEntryIds.length} />
      <FileTreeNodes nodes={tree.nodes} depth={0} navigation={navigation} />
    </div>
  )
}
