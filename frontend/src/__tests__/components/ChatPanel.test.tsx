import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChatPanel } from '../../components/ChatPanel'
import type { ChatMessage } from '../../types'

describe('ChatPanel', () => {
  const defaultProps = {
    messages: [] as ChatMessage[],
    onSend: vi.fn(),
    isRunning: false,
  }

  it('renders empty state when no messages', () => {
    render(<ChatPanel {...defaultProps} />)
    expect(screen.getByText('Desktop Agent 就绪')).toBeInTheDocument()
  })

  it('renders user message', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: 'Hello', isTool: false },
    ]
    render(<ChatPanel {...defaultProps} messages={messages} />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })

  it('renders assistant message', () => {
    const messages: ChatMessage[] = [
      { role: 'assistant', content: 'Hi there', isTool: false },
    ]
    render(<ChatPanel {...defaultProps} messages={messages} />)
    expect(screen.getByText('Hi there')).toBeInTheDocument()
  })

  it('calls onSend when clicking send button', () => {
    const onSend = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} />)

    const input = screen.getByPlaceholderText('输入指令... (Shift+Enter 换行)')
    fireEvent.change(input, { target: { value: 'test message' } })

    const buttons = screen.getAllByRole('button')
    const sendButton = buttons[buttons.length - 1]  // last button is send
    fireEvent.click(sendButton)

    expect(onSend).toHaveBeenCalledWith('test message', undefined)
  })

  it('calls onSend when pressing Enter', () => {
    const onSend = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} />)

    const input = screen.getByPlaceholderText('输入指令... (Shift+Enter 换行)')
    fireEvent.change(input, { target: { value: 'test message' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onSend).toHaveBeenCalledWith('test message', undefined)
  })

  it('does not call onSend when pressing Shift+Enter', () => {
    const onSend = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} />)

    const input = screen.getByPlaceholderText('输入指令... (Shift+Enter 换行)')
    fireEvent.change(input, { target: { value: 'test message' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })

    expect(onSend).not.toHaveBeenCalled()
  })

  it('shows running indicator', () => {
    render(<ChatPanel {...defaultProps} isRunning={true} />)
    expect(screen.getByText('Agent 思考中...')).toBeInTheDocument()
  })
})
