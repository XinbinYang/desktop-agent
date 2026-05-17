import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ActivityBar } from '../../components/ActivityBar'

describe('ActivityBar', () => {
  const defaultProps = {
    activeSection: 'tools' as const,
    activeAgent: 'personal' as const,
    sidebarCollapsed: false,
    onSectionChange: vi.fn(),
    onAgentChange: vi.fn(),
    onToggleSidebar: vi.fn(),
  }

  it('renders agent entries', () => {
    render(<ActivityBar {...defaultProps} />)
    expect(screen.getByLabelText('Personal Agent')).toBeInTheDocument()
    expect(screen.getByLabelText('Coding Agent')).toBeInTheDocument()
  })

  it('renders all section icons', () => {
    render(<ActivityBar {...defaultProps} />)
    expect(screen.getByLabelText('Tools')).toBeInTheDocument()
    expect(screen.getByLabelText('Project')).toBeInTheDocument()
    expect(screen.getByLabelText('Sessions')).toBeInTheDocument()
    expect(screen.getByLabelText('Knowledge')).toBeInTheDocument()
    expect(screen.getByLabelText('Settings')).toBeInTheDocument()
  })

  it('calls onAgentChange when clicking an agent entry', () => {
    const onAgentChange = vi.fn()
    render(<ActivityBar {...defaultProps} onAgentChange={onAgentChange} sidebarCollapsed={true} />)
    fireEvent.click(screen.getByLabelText('Coding Agent'))
    expect(onAgentChange).toHaveBeenCalledWith('coding')
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
      <ActivityBar {...defaultProps} activeSection="tools" sidebarCollapsed={false} onToggleSidebar={onToggleSidebar} />
    )
    fireEvent.click(screen.getByLabelText('Tools'))
    expect(onToggleSidebar).toHaveBeenCalled()
  })

  it('switches section without toggling for a different section while open', () => {
    const onSectionChange = vi.fn()
    const onToggleSidebar = vi.fn()
    render(
      <ActivityBar {...defaultProps} activeSection="tools" sidebarCollapsed={false}
        onSectionChange={onSectionChange} onToggleSidebar={onToggleSidebar} />
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
