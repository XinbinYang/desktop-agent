import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ProjectPanel } from '../../components/ProjectPanel'

const project = {
  name: 'OPEN AGENT',
  path: 'C:/Users/Harrys/Desktop/OPEN AGENT',
  git_branch: 'main',
  git_modified: 1,
  git_untracked: 2,
  last_opened: '2026-05-18T00:00:00Z',
}

const baseProps = {
  currentProject: project,
  fileTree: [{ name: 'README.md', path: 'README.md', type: 'file' as const, extension: 'md' }],
  expandedPaths: new Set<string>(),
  onTogglePath: vi.fn(),
  onSelectFile: vi.fn(),
  onOpenFolder: vi.fn(),
  onOpenModal: vi.fn(),
  onCloseProject: vi.fn(),
  onRefreshTree: vi.fn(async () => undefined),
}

describe('ProjectPanel', () => {
  it('renders a clear refresh button and calls refresh', () => {
    const onRefreshTree = vi.fn()
    render(<ProjectPanel {...baseProps} onRefreshTree={onRefreshTree} />)

    fireEvent.click(screen.getByLabelText('刷新项目文件'))

    expect(onRefreshTree).toHaveBeenCalledOnce()
  })

  it('disables and spins the refresh button while refreshing', () => {
    const { container } = render(<ProjectPanel {...baseProps} isRefreshing />)

    expect(screen.getByLabelText('刷新项目文件')).toBeDisabled()
    expect(container.querySelector('.animate-spin')).toBeTruthy()
  })
})
