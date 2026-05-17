import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Sidebar } from '../../components/Sidebar'

describe('Sidebar', () => {
  const defaultProps = {
    activeSection: 'tools' as const,
    activeAgent: 'personal' as const,
    onSectionChange: vi.fn(),
    agentModel: 'gpt-4o',
    onOpenPersonalWorkspace: vi.fn(),
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
    expect(screen.getByText('Active Agent')).toBeInTheDocument()
    expect(screen.getByText('Open Full Settings')).toBeInTheDocument()
  })

  it('calls onOpenSettings when clicking open settings button', () => {
    const onOpenSettings = vi.fn()
    render(<Sidebar {...defaultProps} activeSection="settings" onOpenSettings={onOpenSettings} />)

    fireEvent.click(screen.getByText('Open Full Settings'))

    expect(onOpenSettings).toHaveBeenCalled()
  })

  it('does not expose the legacy role selector in settings section', () => {
    render(<Sidebar {...defaultProps} activeSection="settings" />)

    expect(screen.queryByLabelText('Select role')).not.toBeInTheDocument()
  })

  it('shows knowledge content when activeSection is knowledge', () => {
    render(<Sidebar {...defaultProps} activeSection="knowledge" />)
    expect(screen.getByText('Knowledge Base')).toBeInTheDocument()
    expect(screen.getByText('View All Documents')).toBeInTheDocument()
  })

  it('calls onClear when clicking clear button', () => {
    const onClear = vi.fn()
    render(<Sidebar {...defaultProps} onClear={onClear} />)

    fireEvent.click(screen.getByText('Clear Session'))

    expect(onClear).toHaveBeenCalled()
  })

  it('calls onExecuteTool when clicking quick tool', () => {
    const onExecuteTool = vi.fn()
    render(<Sidebar {...defaultProps} onExecuteTool={onExecuteTool} />)

    fireEvent.click(screen.getByText('Screenshot'))

    expect(onExecuteTool).toHaveBeenCalledWith('screenshot', {})
  })

  it('shows connected status', () => {
    render(<Sidebar {...defaultProps} isConnected />)
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
