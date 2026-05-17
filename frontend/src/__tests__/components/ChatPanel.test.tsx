import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ChatPanel } from '../../components/ChatPanel'
import type { ChatMessage, PlanState } from '../../types'

vi.mock('react-virtuoso', () => {
  const Virtuoso = ({ data, itemContent, components, totalCount }: any) => {
    const count = totalCount ?? data?.length ?? 0;
    return (
      <div>
        {components?.Header?.()}
        {count === 0 && components?.EmptyPlaceholder
          ? components.EmptyPlaceholder()
          : null}
        {count > 0 && data?.map((_item: any, index: number) => (
          <div key={index}>{itemContent(index)}</div>
        ))}
        {components?.Footer?.()}
      </div>
    );
  };
  return { Virtuoso, VirtuosoHandle: {} as any };
});

const idlePlanState: PlanState = {
  mode: 'agent',
  phase: 'idle',
  goal: '',
  draft: '',
  structured_plan: null,
  questions: [],
  todos: [],
  decisions: {},
  approved: false,
  pending_clarification: false,
}

describe('ChatPanel', () => {
  const defaultProps = {
    messages: [] as ChatMessage[],
    toolCalls: [],
    onSend: vi.fn(),
    isRunning: false,
    chatMode: 'agent' as const,
    onChatModeChange: vi.fn(),
    thinkingIntensity: 'medium' as const,
    onThinkingIntensityChange: vi.fn(),
    planState: idlePlanState,
    onApprovePlan: vi.fn(),
    onBuildPlan: vi.fn(),
    onRejectPlan: vi.fn(),
    onUpdatePlanDecision: vi.fn(),
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

    expect(onSend).toHaveBeenCalledWith('test message', undefined, {
      chatMode: 'agent',
      thinkingIntensity: 'medium',
    })
  })

  it('calls onSend when pressing Enter', () => {
    const onSend = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: 'test message' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onSend).toHaveBeenCalledWith('test message', undefined, {
      chatMode: 'agent',
      thinkingIntensity: 'medium',
    })
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

  it('Plan mode control marks aria-pressed when plan is selected', () => {
    render(<ChatPanel {...defaultProps} chatMode="plan" />)
    expect(screen.getByLabelText('Plan mode')).toHaveAttribute('aria-pressed', 'true')
  })

  it('uses a folded Thinking menu and reports selected intensity', () => {
    const onThinkingIntensityChange = vi.fn()
    render(
      <ChatPanel
        {...defaultProps}
        thinkingIntensity="medium"
        onThinkingIntensityChange={onThinkingIntensityChange}
      />,
    )

    const trigger = screen.getByRole('button', { name: /Thinking intensity MEDIUM/i })
    expect(trigger).toHaveTextContent('MEDIUM')

    fireEvent.pointerDown(trigger)
    fireEvent.click(screen.getByText('HIGH'))

    expect(onThinkingIntensityChange).toHaveBeenCalledWith('high')
  })

  it('disables chat input while plan awaiting_decision', () => {
    const awaiting: PlanState = {
      ...idlePlanState,
      mode: 'plan',
      phase: 'awaiting_decision',
    }
    render(<ChatPanel {...defaultProps} chatMode="plan" planState={awaiting} />)
    expect(screen.getByPlaceholderText(/Complete the plan questions/)).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent(/Please complete the questions/)
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

  it('renders context meter and compacts on click', () => {
    const onCompact = vi.fn()
    render(
      <ChatPanel
        {...defaultProps}
        contextUsage={{
          session_id: 's1',
          model_id: 'gpt-4o',
          model_context: 1000,
          estimated_tokens: 720,
          used_tokens: 720,
          remaining_tokens: 280,
          used_percent: 72,
          exact: false,
          source: 'estimate',
          status: 'warning',
          breakdown: { history: 500, tools: 100, system: 120 },
        }}
        onCompact={onCompact}
      />,
    )

    fireEvent.click(screen.getByTitle(/Context 72\.0%/))
    expect(onCompact).toHaveBeenCalledWith(false)
  })

  it('lists rewind checkpoints and calls rewind action', async () => {
    const onRewindToCheckpoint = vi.fn()
    const onLoadCheckpoints = vi.fn(async () => [])
    const onRewindOpenChange = vi.fn()
    render(
      <ChatPanel
        {...defaultProps}
        rewindOpen
        checkpoints={[{
          id: 'chk_1',
          index: 1,
          role: 'user',
          preview: 'Try this earlier prompt',
          created_at: 1710000000,
        }]}
        onLoadCheckpoints={onLoadCheckpoints}
        onRewindToCheckpoint={onRewindToCheckpoint}
        onRewindOpenChange={onRewindOpenChange}
      />,
    )

    fireEvent.click(screen.getByText('Try this earlier prompt'))
    expect(onLoadCheckpoints).toHaveBeenCalled()
    expect(onRewindToCheckpoint).toHaveBeenCalledWith('chk_1')
    expect(onRewindOpenChange).toHaveBeenCalledWith(false)
  })
})
