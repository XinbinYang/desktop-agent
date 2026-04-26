import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Sidebar } from '../../components/Sidebar'
import type { ModelInfo } from '../../types'

describe('Sidebar', () => {
  const mockModels: ModelInfo[] = [
    { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
    { id: 'claude-3', name: 'Claude 3', provider: 'anthropic', vision: true, context: 200000 },
  ]

  const defaultProps = {
    models: mockModels,
    currentModel: 'gpt-4o',
    onModelChange: vi.fn(),
    onClear: vi.fn(),
    onToggleTerminal: vi.fn(),
    onExecuteTool: vi.fn(),
    isConnected: true,
  }

  it('renders quick tools list', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('截图')).toBeInTheDocument()
    expect(screen.getByText('打开浏览器')).toBeInTheDocument()
  })

  it('calls onModelChange when selecting different model', () => {
    const onModelChange = vi.fn()
    render(<Sidebar {...defaultProps} onModelChange={onModelChange} />)

    // Switch to settings tab first
    const settingsTab = screen.getByText('设置')
    fireEvent.click(settingsTab)

    const select = screen.getByDisplayValue('GPT-4o')
    fireEvent.change(select, { target: { value: 'claude-3' } })

    expect(onModelChange).toHaveBeenCalledWith('claude-3')
  })

  it('calls onClear when clicking clear button', () => {
    const onClear = vi.fn()
    render(<Sidebar {...defaultProps} onClear={onClear} />)

    const clearButton = screen.getByText('清空会话')
    fireEvent.click(clearButton)

    expect(onClear).toHaveBeenCalled()
  })

  it('calls onExecuteTool when clicking quick tool', () => {
    const onExecuteTool = vi.fn()
    render(<Sidebar {...defaultProps} onExecuteTool={onExecuteTool} />)

    const screenshotBtn = screen.getByText('截图')
    fireEvent.click(screenshotBtn)

    expect(onExecuteTool).toHaveBeenCalledWith('screenshot', {})
  })

  it('shows connected status', () => {
    render(<Sidebar {...defaultProps} isConnected={true} />)
    expect(screen.getByText('已连接')).toBeInTheDocument()
  })

  it('shows disconnected status', () => {
    render(<Sidebar {...defaultProps} isConnected={false} />)
    expect(screen.getByText('未连接')).toBeInTheDocument()
  })
})
