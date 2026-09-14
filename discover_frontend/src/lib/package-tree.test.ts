import { describe, expect, it } from 'vitest'
import {
  buildPackageTree,
  countPackageFiles,
  packageEntriesFromDetail,
  removePackageEntryAndEmptyDirectories,
} from '@/lib/package-tree'
import type { PackageDetail, PackageEntry } from '@/types'

function makeEntry(overrides: Partial<PackageEntry>): PackageEntry {
  return {
    entry_id: 1,
    parent_id: null,
    entry_type: 'file',
    name: 'file.md',
    path: 'file.md',
    content: '',
    sort_order: 0,
    ...overrides,
  }
}

describe('buildPackageTree', () => {
  it('按 parent_id 构建目录树，忽略根节点并按 sort_order 排序', () => {
    const entries: PackageEntry[] = [
      makeEntry({
        entry_id: 1,
        entry_type: 'directory',
        name: '',
        path: '',
        content: null,
      }),
      makeEntry({ entry_id: 2, parent_id: 1, name: 'AGENT.md', path: 'AGENT.md', sort_order: 2 }),
      makeEntry({
        entry_id: 3,
        parent_id: 1,
        entry_type: 'directory',
        name: 'client-finder',
        path: 'client-finder',
        content: null,
        sort_order: 1,
      }),
      makeEntry({
        entry_id: 4,
        parent_id: 3,
        name: 'z.md',
        path: 'client-finder/z.md',
        sort_order: 2,
      }),
      makeEntry({
        entry_id: 5,
        parent_id: 3,
        name: 'a.md',
        path: 'client-finder/a.md',
        sort_order: 1,
      }),
    ]

    const result = buildPackageTree(entries)

    expect(result.orphanEntryIds).toEqual([])
    expect(result.nodes.map((node) => `${node.kind}:${node.entry.name}`)).toEqual([
      'directory:client-finder',
      'file:AGENT.md',
    ])
    expect(result.nodes[0]).toMatchObject({
      kind: 'directory',
      children: [
        { kind: 'file', entry: { name: 'a.md' } },
        { kind: 'file', entry: { name: 'z.md' } },
      ],
    })
  })

  it('父节点缺失时返回异常节点，不静默丢弃', () => {
    const result = buildPackageTree([
      makeEntry({ entry_id: 9, parent_id: 999, name: 'orphan.md', path: 'lost/orphan.md' }),
    ])

    expect(result.nodes).toEqual([])
    expect(result.orphanEntryIds).toEqual([9])
  })

  it('文件数量只统计 file 节点', () => {
    const entries: PackageEntry[] = [
      makeEntry({ entry_id: 1, entry_type: 'directory', name: '', path: '', content: null }),
      makeEntry({
        entry_id: 2,
        parent_id: 1,
        entry_type: 'directory',
        name: 'references',
        path: 'references',
        content: null,
      }),
      makeEntry({
        entry_id: 3,
        parent_id: 2,
        name: 'guide.md',
        path: 'references/guide.md',
      }),
    ]

    expect(countPackageFiles(entries)).toBe(1)
  })
})

describe('removePackageEntryAndEmptyDirectories', () => {
  it('删除最后一个文件时同步移除空目录', () => {
    const entries: PackageEntry[] = [
      makeEntry({ entry_id: 1, entry_type: 'directory', name: '', path: '', content: null }),
      makeEntry({
        entry_id: 2,
        parent_id: 1,
        entry_type: 'directory',
        name: 'references',
        path: 'references',
        content: null,
      }),
      makeEntry({
        entry_id: 3,
        parent_id: 2,
        name: 'guide.md',
        path: 'references/guide.md',
      }),
    ]

    const remaining = removePackageEntryAndEmptyDirectories(entries, 'references/guide.md')

    expect(remaining.map((entry) => entry.entry_id)).toEqual([1])
  })
})

describe('packageEntriesFromDetail', () => {
  it('entries 缺失时兼容投影旧 files', () => {
    const detail: PackageDetail = {
      package_id: 'pkg-1',
      agent_id: 'client-finder',
      version: '1.0.0',
      status: 'draft',
      enabled: false,
      files: [
        { path: 'AGENT.md', content: 'agent' },
        { path: 'client-finder/references/architecture.md', content: 'rules' },
      ],
      published_at: null,
      updated_at: '2026-09-14T00:00:00Z',
    }

    const entries = packageEntriesFromDetail(detail)
    const result = buildPackageTree(entries)

    expect(result.nodes.map((node) => `${node.kind}:${node.entry.name}`)).toEqual([
      'directory:client-finder',
      'file:AGENT.md',
    ])
    expect(result.nodes[0]).toMatchObject({
      kind: 'directory',
      children: [
        {
          kind: 'directory',
          entry: { name: 'references' },
          children: [{ kind: 'file', entry: { name: 'architecture.md' } }],
        },
      ],
    })
  })
})
