import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
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

  it('shows file actions from the project tree context menu', () => {
    const onFileAction = vi.fn()
    const node = { name: 'test_app.py', path: 'tests/test_app.py', type: 'file' as const, extension: 'py' }
    render(<ProjectPanel {...baseProps} fileTree={[node]} onFileAction={onFileAction} />)

    fireEvent.contextMenu(screen.getByText('test_app.py'))

    const menu = screen.getByRole('menu', { name: '文件操作菜单' })
    expect(within(menu).getByText('打开')).toBeInTheDocument()
    expect(within(menu).getByText('打开到侧边')).toBeInTheDocument()
    expect(within(menu).getByText('运行文件')).toBeInTheDocument()
    fireEvent.click(within(menu).getByText('运行测试'))

    expect(onFileAction).toHaveBeenCalledWith('run_tests', node)
  })

  it('shows directory actions from the project tree context menu', () => {
    const onFileAction = vi.fn()
    const node = { name: 'src', path: 'src', type: 'dir' as const, has_children: true }
    render(<ProjectPanel {...baseProps} fileTree={[node]} onFileAction={onFileAction} />)

    fireEvent.contextMenu(screen.getByText('src'))

    const menu = screen.getByRole('menu', { name: '文件操作菜单' })
    expect(within(menu).getByText('展开')).toBeInTheDocument()
    expect(within(menu).queryByText('打开到侧边')).toBeNull()
    fireEvent.click(within(menu).getByText('运行该目录测试'))

    expect(onFileAction).toHaveBeenCalledWith('run_tests', node)
  })
})
