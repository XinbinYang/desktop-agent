import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Sidebar } from '../../components/Sidebar'
import type { RoleInfo } from '../../types'

describe('Sidebar', () => {
  const mockRoles: RoleInfo[] = [
    { id: 'desktop-agent', name: '桌面助手', description: '全能助手', isBuiltin: true },
    { id: 'code-expert', name: '代码专家', description: '专注代码', isBuiltin: true },
  ]

  const defaultProps = {
    activeSection: 'tools' as const,
    onSectionChange: vi.fn(),
    roles: mockRoles,
    currentRole: 'desktop-agent',
    onRoleChange: vi.fn(),
    onOpenRoleEditor: vi.fn(),
    onOpenSettings: vi.fn(),
    onClear: vi.fn(),
    onExecuteTool: vi.fn(),
    isConnected: true,
  }

  it('renders quick tools list', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('Screenshot')).toBeInTheDocument()
    expect(screen.getByText('Open Browser')).toBeInTheDocument()
  })

  it('shows settings content when activeSection is settings', () => {
    render(<Sidebar {...defaultProps} activeSection="settings" />)
    expect(screen.getByText('Open Full Settings')).toBeInTheDocument()
  })

  it('calls onOpenSettings when clicking open settings button', () => {
    const onOpenSettings = vi.fn()
    render(<Sidebar {...defaultProps} activeSection="settings" onOpenSettings={onOpenSettings} />)

    const openBtn = screen.getByText('Open Full Settings')
    fireEvent.click(openBtn)

    expect(onOpenSettings).toHaveBeenCalled()
  })

  it('shows role selector in settings section', () => {
    render(<Sidebar {...defaultProps} activeSection="settings" />)

    expect(screen.getByDisplayValue('桌面助手')).toBeInTheDocument()
  })

  it('shows knowledge content when activeSection is knowledge', () => {
    render(<Sidebar {...defaultProps} activeSection="knowledge" />)
    expect(screen.getByText('Knowledge Base')).toBeInTheDocument()
    expect(screen.getByText('View All Documents')).toBeInTheDocument()
  })

  it('calls onClear when clicking clear button', () => {
    const onClear = vi.fn()
    render(<Sidebar {...defaultProps} onClear={onClear} />)

    const clearButton = screen.getByText('Clear Session')
    fireEvent.click(clearButton)

    expect(onClear).toHaveBeenCalled()
  })

  it('calls onExecuteTool when clicking quick tool', () => {
    const onExecuteTool = vi.fn()
    render(<Sidebar {...defaultProps} onExecuteTool={onExecuteTool} />)

    const screenshotBtn = screen.getByText('Screenshot')
    fireEvent.click(screenshotBtn)

    expect(onExecuteTool).toHaveBeenCalledWith('screenshot', {})
  })

  it('shows connected status', () => {
    render(<Sidebar {...defaultProps} isConnected={true} />)
    expect(screen.getByText('Connected')).toBeInTheDocument()
  })

  it('shows disconnected status', () => {
    render(<Sidebar {...defaultProps} isConnected={false} />)
    expect(screen.getByText('Disconnected')).toBeInTheDocument()
  })

  it('does not render tab buttons (moved to ActivityBar)', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.queryByRole('button', { name: 'Tools' })).not.toBeInTheDocument()
  })
})
