import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ActivityBar } from '../../components/ActivityBar'

describe('ActivityBar', () => {
  const defaultProps = {
    activeSection: 'tools' as const,
    sidebarCollapsed: false,
    onSectionChange: vi.fn(),
    onToggleSidebar: vi.fn(),
  }

  it('renders all 5 section icons', () => {
    render(<ActivityBar {...defaultProps} />)
    expect(screen.getByLabelText('Tools')).toBeInTheDocument()
    expect(screen.getByLabelText('Project')).toBeInTheDocument()
    expect(screen.getByLabelText('Sessions')).toBeInTheDocument()
    expect(screen.getByLabelText('Knowledge')).toBeInTheDocument()
    expect(screen.getByLabelText('Settings')).toBeInTheDocument()
  })

  it('shows panel close icon when sidebar is open', () => {
    render(<ActivityBar {...defaultProps} sidebarCollapsed={false} />)
    expect(screen.getByLabelText('Collapse Sidebar')).toBeInTheDocument()
  })

  it('shows panel open icon when sidebar is collapsed', () => {
    render(<ActivityBar {...defaultProps} sidebarCollapsed={true} />)
    expect(screen.getByLabelText('Expand Sidebar')).toBeInTheDocument()
  })

  it('calls onSectionChange when clicking a section icon', () => {
    const onSectionChange = vi.fn()
    render(<ActivityBar {...defaultProps} onSectionChange={onSectionChange} />)

    fireEvent.click(screen.getByLabelText('Settings'))
    expect(onSectionChange).toHaveBeenCalledWith('settings')
  })

  it('calls onToggleSidebar when clicking the same active section', () => {
    const onToggleSidebar = vi.fn()
    render(
      <ActivityBar
        {...defaultProps}
        activeSection="tools"
        sidebarCollapsed={false}
        onToggleSidebar={onToggleSidebar}
      />
    )

    fireEvent.click(screen.getByLabelText('Tools'))
    expect(onToggleSidebar).toHaveBeenCalled()
  })

  it('expands sidebar when clicking an icon while collapsed', () => {
    const onSectionChange = vi.fn()
    const onToggleSidebar = vi.fn()
    render(
      <ActivityBar
        {...defaultProps}
        activeSection="tools"
        sidebarCollapsed={true}
        onSectionChange={onSectionChange}
        onToggleSidebar={onToggleSidebar}
      />
    )

    fireEvent.click(screen.getByLabelText('Project'))
    expect(onSectionChange).toHaveBeenCalledWith('project')
    expect(onToggleSidebar).toHaveBeenCalled()
  })

  it('switches section without toggling for a different section while open', () => {
    const onSectionChange = vi.fn()
    const onToggleSidebar = vi.fn()
    render(
      <ActivityBar
        {...defaultProps}
        activeSection="tools"
        sidebarCollapsed={false}
        onSectionChange={onSectionChange}
        onToggleSidebar={onToggleSidebar}
      />
    )

    fireEvent.click(screen.getByLabelText('Sessions'))
    expect(onSectionChange).toHaveBeenCalledWith('sessions')
    expect(onToggleSidebar).not.toHaveBeenCalled()
  })

  it('calls onToggleSidebar when clicking bottom toggle button', () => {
    const onToggleSidebar = vi.fn()
    render(<ActivityBar {...defaultProps} onToggleSidebar={onToggleSidebar} />)

    fireEvent.click(screen.getByLabelText('Collapse Sidebar'))
    expect(onToggleSidebar).toHaveBeenCalled()
  })
})
