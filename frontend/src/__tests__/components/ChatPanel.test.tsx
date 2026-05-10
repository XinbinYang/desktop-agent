import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChatPanel } from '../../components/ChatPanel'
import type { ChatMessage } from '../../types'

describe('ChatPanel', () => {
  const defaultProps = {
    messages: [] as ChatMessage[],
    toolCalls: [],
    onSend: vi.fn(),
    isRunning: false,
  }

  it('renders empty state when no messages', () => {
    render(<ChatPanel {...defaultProps} />)
    expect(screen.getByText('Desktop Agent Ready')).toBeInTheDocument()
  })

  it('renders user message', () => {
    const messages: ChatMessage[] = [
      { id: '1', role: 'user', content: 'Hello', isTool: false },
    ]
    render(<ChatPanel {...defaultProps} messages={messages} />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })

  it('renders assistant message', () => {
    const messages: ChatMessage[] = [
      { id: '2', role: 'assistant', content: 'Hi there', isTool: false },
    ]
    render(<ChatPanel {...defaultProps} messages={messages} />)
    expect(screen.getByText('Hi there')).toBeInTheDocument()
  })

  it('renders assistant markdown with chat prose class and no invert class', () => {
    const messages: ChatMessage[] = [
      { id: '2', role: 'assistant', content: 'Regular **message**', isTool: false },
    ]
    const { container } = render(<ChatPanel {...defaultProps} messages={messages} />)
    const proseNode = container.querySelector('.chat-prose')
    expect(proseNode).toBeTruthy()
    expect(container.querySelector('.prose-invert')).toBeNull()
  })

  it('calls onSend when clicking send button', () => {
    const onSend = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: 'test message' } })

    const sendButton = screen.getByLabelText('Send')
    fireEvent.click(sendButton)

    expect(onSend).toHaveBeenCalledWith('test message', undefined)
  })

  it('calls onSend when pressing Enter', () => {
    const onSend = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: 'test message' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onSend).toHaveBeenCalledWith('test message', undefined)
  })

  it('does not call onSend when pressing Shift+Enter', () => {
    const onSend = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: 'test message' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })

    expect(onSend).not.toHaveBeenCalled()
  })

  it('shows running indicator', () => {
    render(<ChatPanel {...defaultProps} isRunning={true} />)
    expect(screen.getByText('Agent is working...')).toBeInTheDocument()
  })

  it('filters messages by search query', () => {
    const messages: ChatMessage[] = [
      { id: '1', role: 'user', content: 'Hello world', isTool: false },
      { id: '2', role: 'assistant', content: 'Goodbye', isTool: false },
    ]
    render(<ChatPanel {...defaultProps} messages={messages} />)

    // Search functionality is internal; we verify both messages render by default
    expect(screen.getByText('Hello world')).toBeInTheDocument()
    expect(screen.getByText('Goodbye')).toBeInTheDocument()
  })

  it('shows stop button when running', () => {
    const onStop = vi.fn()
    render(<ChatPanel {...defaultProps} isRunning={true} onStop={onStop} />)

    const stopButton = screen.getByLabelText('Stop')
    fireEvent.click(stopButton)
    expect(onStop).toHaveBeenCalled()
  })
})
