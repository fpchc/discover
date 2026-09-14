import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { PackageFileTree } from '@/components/admin/PackageFileTree'
import type { PackageEntry } from '@/types'

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

const entries: PackageEntry[] = [
  makeEntry({ entry_id: 10, entry_type: 'directory', name: '', path: '', content: null }),
  makeEntry({
    entry_id: 20,
    parent_id: 10,
    entry_type: 'directory',
    name: 'client-finder',
    path: 'client-finder',
    content: null,
  }),
  makeEntry({
    entry_id: 30,
    parent_id: 20,
    name: 'SKILL.md',
    path: 'client-finder/SKILL.md',
  }),
]

describe('PackageFileTree', () => {
  it('根节点隐藏，目录只切换展开，文件才触发选择', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    const onSelect = vi.fn()

    render(
      <PackageFileTree
        entries={entries}
        selectedEntryId={30}
        collapsedEntryIds={new Set()}
        onToggle={onToggle}
        onSelect={onSelect}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'client-finder' }))
    expect(onToggle).toHaveBeenCalledWith(20)
    expect(onSelect).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'SKILL.md' }))
    expect(onSelect).toHaveBeenCalledWith(30)
  })
})
