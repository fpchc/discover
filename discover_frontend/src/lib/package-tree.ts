import type { PackageDetail, PackageEntry, PackageFile } from '@/types'

export interface PackageTreeDirectory {
  kind: 'directory'
  entry: PackageEntry
  children: PackageTreeNode[]
}

export interface PackageTreeFile {
  kind: 'file'
  entry: PackageEntry
}

export type PackageTreeNode = PackageTreeDirectory | PackageTreeFile

export interface PackageTreeBuildResult {
  nodes: PackageTreeNode[]
  /** 父节点缺失或父节点不是目录的异常节点 ID，不应静默丢弃 */
  orphanEntryIds: number[]
}

function isPackageRoot(entry: PackageEntry): boolean {
  return entry.parent_id === null && entry.entry_type === 'directory' && entry.name === ''
}

function compareTreeNodes(left: PackageTreeNode, right: PackageTreeNode): number {
  if (left.kind !== right.kind) return left.kind === 'directory' ? -1 : 1
  const orderDelta = left.entry.sort_order - right.entry.sort_order
  if (orderDelta !== 0) return orderDelta
  return left.entry.name.localeCompare(right.entry.name, 'zh-CN')
}

/** 按 entry_id / parent_id 构建技能包树；root 节点仅用于挂载，不进入展示树。 */
export function buildPackageTree(entries: PackageEntry[]): PackageTreeBuildResult {
  const entryById = new Map(entries.map((entry) => [entry.entry_id, entry]))
  const root = entries.find(isPackageRoot)
  const childrenByParent = new Map<number, PackageEntry[]>()
  const visited = new Set<number>()

  for (const entry of entries) {
    if (root !== undefined && entry.entry_id === root.entry_id) continue
    if (entry.parent_id === null) continue
    const parent = entryById.get(entry.parent_id)
    if (parent === undefined || parent.entry_type !== 'directory') continue
    const siblings = childrenByParent.get(parent.entry_id) ?? []
    siblings.push(entry)
    childrenByParent.set(parent.entry_id, siblings)
  }

  function materialize(source: PackageEntry[]): PackageTreeNode[] {
    const nodes = source.map((entry): PackageTreeNode => {
      visited.add(entry.entry_id)
      if (entry.entry_type === 'file') return { kind: 'file', entry }
      return {
        kind: 'directory',
        entry,
        children: materialize(childrenByParent.get(entry.entry_id) ?? []),
      }
    })
    return nodes.sort(compareTreeNodes)
  }

  if (root !== undefined) visited.add(root.entry_id)
  const topLevel =
    root === undefined
      ? entries.filter((entry) => entry.parent_id === null)
      : (childrenByParent.get(root.entry_id) ?? [])
  const nodes = materialize(topLevel)
  const orphanEntryIds = entries
    .filter((entry) => !visited.has(entry.entry_id))
    .map((entry) => entry.entry_id)

  return { nodes, orphanEntryIds }
}

/** 文件数量只统计 file 节点，根节点与目录节点不计入。 */
export function countPackageFiles(entries: PackageEntry[]): number {
  return entries.filter((entry) => entry.entry_type === 'file').length
}

/** entries 为唯一事实源；仅旧后端缺少 entries 时用 files 投影兼容树。 */
export function packageEntriesFromDetail(detail: PackageDetail): PackageEntry[] {
  if (detail.entries !== undefined) return detail.entries
  return packageFilesToEntries(detail.files ?? [])
}

function packageFilesToEntries(files: PackageFile[]): PackageEntry[] {
  const entries: PackageEntry[] = []
  const directories = new Map<string, PackageEntry>()
  const usedIds = new Set<number>()
  const sortedFiles = [...files].sort((left, right) => left.path.localeCompare(right.path, 'zh-CN'))

  for (const file of sortedFiles) {
    // 兼容旧接口时才拆 path；新 entries 结构不会走此分支。
    const segments = file.path.split('/').filter((segment) => segment !== '')
    if (segments.length === 0) continue
    let parentId: number | null = null
    let directoryPath = ''

    for (let index = 0; index < segments.length - 1; index += 1) {
      const segment = segments[index]
      directoryPath = directoryPath === '' ? segment : `${directoryPath}/${segment}`
      let directory = directories.get(directoryPath)
      if (directory === undefined) {
        const entryId = createLegacyEntryId(directoryPath, usedIds)
        directory = {
          entry_id: entryId,
          parent_id: parentId,
          entry_type: 'directory',
          name: segment,
          path: directoryPath,
          content: null,
          sort_order: 0,
        }
        directories.set(directoryPath, directory)
        entries.push(directory)
      }
      parentId = directory.entry_id
    }

    entries.push({
      entry_id: createLegacyEntryId(file.path, usedIds),
      parent_id: parentId,
      entry_type: 'file',
      name: segments[segments.length - 1],
      path: file.path,
      content: file.content,
      sort_order: 0,
    })
  }

  return entries
}

/** 删除文件后移除不再包含任何子节点的祖先目录，与后端级联清理语义一致。 */
export function removePackageEntryAndEmptyDirectories(
  entries: PackageEntry[],
  path: string,
): PackageEntry[] {
  const target = entries.find((entry) => entry.entry_type === 'file' && entry.path === path)
  if (target === undefined) return entries

  const entryById = new Map(entries.map((entry) => [entry.entry_id, entry]))
  let remaining = entries.filter((entry) => entry.entry_id !== target.entry_id)
  let parentId = target.parent_id

  while (parentId !== null) {
    const parent = entryById.get(parentId)
    if (parent === undefined || parent.entry_type !== 'directory' || isPackageRoot(parent)) break
    if (remaining.some((entry) => entry.parent_id === parentId)) break
    remaining = remaining.filter((entry) => entry.entry_id !== parentId)
    parentId = parent.parent_id
  }

  return remaining
}
function createLegacyEntryId(path: string, usedIds: Set<number>): number {
  let hash = 2166136261
  for (let index = 0; index < path.length; index += 1) {
    hash = Math.imul(hash ^ path.charCodeAt(index), 16777619) >>> 0
  }
  let candidate = hash === 0 ? -1 : -hash
  while (usedIds.has(candidate)) candidate -= 1
  usedIds.add(candidate)
  return candidate
}
