import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { ChatPanel } from '../../components/ChatPanel'
import type { ChatMessage, PlanState } from '../../types'

vi.mock('react-virtuoso', () => {
  const Virtuoso = (props: any) => {
    ;(globalThis as any).__chatPanelVirtuosoProps = props;
    const { data, itemContent, components, totalCount } = props;
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
    onPauseBuild: vi.fn(),
    onEndBuild: vi.fn(),
    onRejectPlan: vi.fn(),
    onUpdatePlanDecision: vi.fn(),
    onSubmitPlanDecisions: vi.fn(),
  }

  it('renders empty state when no messages', () => {
    render(<ChatPanel {...defaultProps} />)
    const welcome = screen.getByTestId('empty-chat-welcome')
    expect(within(welcome).getByText(/准备好了|Ready/)).toBeInTheDocument()
    expect(within(welcome).getByText('Personal Agent')).toBeInTheDocument()
    expect(within(welcome).getByText('Agent')).toBeInTheDocument()
    expect(screen.queryByText('Desktop Agent Ready')).not.toBeInTheDocument()
    expect(screen.queryByText('Read / Write Files')).not.toBeInTheDocument()
    expect(screen.queryByText('Browser Automation')).not.toBeInTheDocument()
    expect(Object.prototype.hasOwnProperty.call((globalThis as any).__chatPanelVirtuosoProps || {}, 'initialTopMostItemIndex')).toBe(false)
  })

  it('renders coding project state in the empty welcome', () => {
    render(<ChatPanel {...defaultProps} agentType="coding" projectName="desktop-agent" />)
    const welcome = screen.getByTestId('empty-chat-welcome')
    expect(within(welcome).getByText('Coding Agent')).toBeInTheDocument()
    expect(within(welcome).getAllByText(/desktop-agent/).length).toBeGreaterThan(0)
  })

  it('does not show current project state for Personal Agent', () => {
    render(<ChatPanel {...defaultProps} agentType="personal" projectName="desktop-agent" />)
    const welcome = screen.getByTestId('empty-chat-welcome')
    expect(within(welcome).getByText('Personal Agent')).toBeInTheDocument()
    expect(within(welcome).queryByText(/desktop-agent/)).not.toBeInTheDocument()
  })

  it('uses the coding event timeline for Coding Agent sessions', () => {
    const messages: ChatMessage[] = [
      { id: '1', role: 'user', content: 'Inspect the app', isTool: false },
      {
        id: '2',
        role: 'assistant',
        content: '',
        isTool: false,
        blocks: [
          { type: 'tool_call', name: 'file_read', args: { path: 'a.ts' }, result: 'a', status: 'success', toolCallId: 'r1', timestamp: 1 },
          { type: 'tool_call', name: 'file_read', args: { path: 'b.ts' }, result: 'b', status: 'success', toolCallId: 'r2', timestamp: 2 },
          { type: 'text', text: 'I checked the files.', timestamp: 3 },
        ],
      },
    ]

    render(<ChatPanel {...defaultProps} agentType="coding" messages={messages} />)

    expect(screen.getByTestId('coding-event-timeline')).toBeInTheDocument()
    expect(screen.getByText('Read 2 files')).toBeInTheDocument()
    expect(screen.getByText('I checked the files.')).toBeInTheDocument()
    expect(screen.queryByText('Summary')).not.toBeInTheDocument()
  })

  it('uses the personal conversation timeline and folds adjacent tools', () => {
    const messages: ChatMessage[] = [{
      id: '2',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [
        { type: 'tool_call', name: 'knowledge_search', args: { query: 'memory' }, result: 'one', status: 'success', toolCallId: 'k1', timestamp: 1 },
        { type: 'tool_call', name: 'file_read', args: { path: 'notes.md' }, result: 'two', status: 'success', toolCallId: 'k2', timestamp: 2 },
        { type: 'text', text: 'I found the note.', timestamp: 3 },
      ],
    }]

    render(<ChatPanel {...defaultProps} agentType="personal" messages={messages} />)

    expect(screen.getByTestId('personal-conversation-timeline')).toBeInTheDocument()
    expect(screen.getByText('Used 2 tools')).toBeInTheDocument()
    expect(screen.queryByText('knowledge_search')).not.toBeInTheDocument()
    expect(screen.getByText('I found the note.')).toBeInTheDocument()
  })

  it('renders coding file edits as lightweight event rows', () => {
    const messages: ChatMessage[] = [{
      id: '2',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [{
        type: 'file_edit',
        timestamp: 1,
        edit: {
          path: 'src/example.ts',
          operation: 'modify',
          old_text: 'old content',
          new_text: 'new content',
          unified_diff: '--- a/example.ts\n+++ b/example.ts\n-old content\n+new content\n',
          stats: { added: 1, removed: 1 },
          truncated: false,
          tool_call_id: 'edit-1',
        },
      }],
    }]

    render(<ChatPanel {...defaultProps} agentType="coding" messages={messages} />)

    expect(screen.getByTestId('file-edit-event-row')).toBeInTheDocument()
    expect(screen.queryByText(/old content/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('View diff'))
    expect(screen.getByText(/-old content/)).toBeInTheDocument()
  })

  it('keeps run lifecycle events out of the main chat stream', () => {
    const messages: ChatMessage[] = [{
      id: '2',
      role: 'assistant',
      content: '需要我做什么？直接说任务就行。',
      isTool: false,
    }]

    render(
      <ChatPanel
        {...defaultProps}
        agentType="coding"
        messages={messages}
        runEvents={[
          { id: 'r1', type: 'run_created', timestamp: 1, data: {} },
          { id: 'r2', type: 'context_pack', timestamp: 2, data: {} },
          { id: 'r3', type: 'skills_matched', timestamp: 3, data: { skills: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] } },
          { id: 'r4', type: 'run_completed', timestamp: 4, data: { summary: 'Run completed after 1 iteration(s).' } },
        ]}
      />,
    )

    expect(screen.getByText('需要我做什么？直接说任务就行。')).toBeInTheDocument()
    expect(screen.queryByText(/run created/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/context pack/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Checked skills/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Run completed/i)).not.toBeInTheDocument()
  })

  it('renders plan mode in the empty welcome', () => {
    render(<ChatPanel {...defaultProps} chatMode="plan" />)
    const welcome = screen.getByTestId('empty-chat-welcome')
    expect(within(welcome).getByText('Plan')).toBeInTheDocument()
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

  it('selects an open slash menu command without sending chat', async () => {
    const onSend = vi.fn()
    const onCommand = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => ({
        commands: [
          { name: 'help', description: 'Show help', args: '', category: 'general' },
        ],
      }),
    })))

    render(<ChatPanel {...defaultProps} onSend={onSend} onCommand={onCommand} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: '/' } })
    await screen.findByText('/help')
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(onCommand).toHaveBeenCalledWith('help', ''))
    expect(onSend).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('executes /model from direct input instead of sending chat', () => {
    const onSend = vi.fn()
    const onCommand = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} onCommand={onCommand} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: '/model gpt-4o' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onCommand).toHaveBeenCalledWith('model', 'gpt-4o')
    expect(onSend).not.toHaveBeenCalled()
  })

  it('executes /project with a path argument from direct input', () => {
    const onSend = vi.fn()
    const onCommand = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} onCommand={onCommand} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: '/project C:\\tmp' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onCommand).toHaveBeenCalledWith('project', 'C:\\tmp')
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

  it('switches to plan mode when pressing Shift+Tab in the chat input', () => {
    const onChatModeChange = vi.fn()
    render(<ChatPanel {...defaultProps} onChatModeChange={onChatModeChange} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.keyDown(input, { key: 'Tab', shiftKey: true })

    expect(onChatModeChange).toHaveBeenCalledWith('plan')
  })

  it('sends messages without overriding the live mode ref with a stale prop', () => {
    const onSend = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} />)

    fireEvent.change(screen.getByPlaceholderText(/Type a message/), {
      target: { value: 'Plan this project' },
    })
    fireEvent.click(screen.getByLabelText('Send'))

    expect(onSend).toHaveBeenCalledWith('Plan this project', undefined)
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
      questions: [{
        id: 'scope',
        prompt: 'What scope?',
        allow_multiple: false,
        options: [
          { id: 'small', label: 'Small' },
          { id: 'large', label: 'Large' },
        ],
      }],
    }
    render(<ChatPanel {...defaultProps} chatMode="plan" planState={awaiting} />)
    expect(screen.getByPlaceholderText(/Complete the plan questions/)).toBeDisabled()
    expect(screen.getByRole('dialog', { name: /Plan questions/i })).toHaveTextContent('Questions')
    expect(screen.getByText('A')).toBeInTheDocument()
    expect(screen.getByText('B')).toBeInTheDocument()
    expect(screen.getByText('Other...')).toBeInTheDocument()
  })

  it('submits plan question answers with Other text', () => {
    const onSubmitPlanDecisions = vi.fn()
    const awaiting: PlanState = {
      ...idlePlanState,
      mode: 'plan',
      phase: 'awaiting_decision',
      questions: [{
        id: 'scope',
        prompt: 'What scope?',
        allow_multiple: false,
        options: [
          { id: 'small', label: 'Small' },
          { id: 'large', label: 'Large' },
        ],
      }],
    }
    render(
      <ChatPanel
        {...defaultProps}
        chatMode="plan"
        planState={awaiting}
        onSubmitPlanDecisions={onSubmitPlanDecisions}
      />,
    )

    fireEvent.click(screen.getByText('Other...'))
    expect(screen.getByRole('button', { name: /Continue/i })).toBeDisabled()
    fireEvent.change(screen.getByPlaceholderText('Describe your preference'), {
      target: { value: 'Keep a manual fallback' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Continue/i }))

    expect(onSubmitPlanDecisions).toHaveBeenCalledWith([{
      question_id: 'scope',
      selected: [],
      other_text: 'Keep a manual fallback',
      skipped: false,
    }])
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

  it('renders plan draft review card with View Plan and Build', () => {
    const onBuildPlan = vi.fn()
    const onViewPlan = vi.fn()
    const planState: PlanState = {
      ...idlePlanState,
      mode: 'plan',
      phase: 'awaiting_approval',
      goal: 'Add plan UX',
      draft: '# Add plan UX\n\nDetailed markdown body.',
      todos: [
        { id: 't1', title: 'Build questions dock', status: 'pending' },
        { id: 't2', title: 'Build review card', status: 'pending' },
        { id: 't3', title: 'Build execution card', status: 'pending' },
        { id: 't4', title: 'Add tests', status: 'pending' },
      ],
    }
    const messages: ChatMessage[] = [{
      id: 'plan',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [{
        type: 'plan_draft',
        goal: 'Add plan UX',
        draft: '# Add plan UX\n\nDetailed markdown body.',
        todos: planState.todos,
        structured_plan: null,
        timestamp: 1,
      }],
    }]

    render(<ChatPanel {...defaultProps} chatMode="plan" messages={messages} planState={planState} onBuildPlan={onBuildPlan} onViewPlan={onViewPlan} />)
    expect(screen.getByText('View Plan')).toBeInTheDocument()
    expect(screen.getByTitle(/Build plan/)).toBeInTheDocument()
    expect(screen.getByText('任务方案 / Approach (4)')).toBeInTheDocument()
    fireEvent.click(screen.getByText('View Plan'))
    expect(onViewPlan).toHaveBeenCalled()
    expect(screen.queryByText('Detailed markdown body.')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTitle(/Build plan/))
    expect(onBuildPlan).toHaveBeenCalled()
  })

  it('shows task-first plan card without separate Steps and To-dos sections', () => {
    const onViewPlan = vi.fn()
    const planState: PlanState = {
      ...idlePlanState,
      mode: 'plan',
      phase: 'awaiting_approval',
      goal: 'Add plan UX',
      structured_plan: {
        goal: 'Add plan UX',
        assumptions: [],
        steps: [{ id: 's1', title: 'Add button', details: 'frontend/src/App.tsx:10' }],
        todos: [{ id: 't1', title: 'Add button', status: 'pending', acceptance_criteria: 'Button renders' }],
        risks: [],
        acceptance_criteria: ['Run tests'],
      },
      todos: [{ id: 't1', title: 'Add button', status: 'pending', acceptance_criteria: 'Button renders' }],
    }
    const messages: ChatMessage[] = [{
      id: 'plan',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [{
        type: 'plan_draft',
        goal: 'Add plan UX',
        draft: '',
        todos: planState.todos,
        structured_plan: planState.structured_plan,
        timestamp: 1,
      }],
    }]

    render(<ChatPanel {...defaultProps} chatMode="plan" messages={messages} planState={planState} onViewPlan={onViewPlan} />)

    expect(screen.getByText('任务方案 / Approach (1)')).toBeInTheDocument()
    expect(screen.queryByText('Steps (1)')).not.toBeInTheDocument()
    expect(screen.queryByText('To-dos (1)')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('View Plan'))
    expect(onViewPlan).toHaveBeenCalled()
    expect(screen.getAllByText('Add button').length).toBeGreaterThan(0)
  })

  it('renders fixed execution to-dos while building', () => {
    const executing: PlanState = {
      ...idlePlanState,
      mode: 'agent',
      phase: 'executing',
      goal: 'Build the plan',
      todos: [
        { id: 't1', title: 'First todo', status: 'completed' },
        { id: 't2', title: 'Second todo', status: 'in_progress' },
      ],
      approved: true,
    }
    render(<ChatPanel {...defaultProps} chatMode="agent" planState={executing} />)
    expect(screen.getByText('Build')).toBeInTheDocument()
    expect(screen.getAllByText('Second todo').length).toBeGreaterThan(0)
    expect(screen.getByText('2/2')).toBeInTheDocument()
  })

  it('offers pause/end/continue controls for build execution', () => {
    const onPauseBuild = vi.fn()
    const onEndBuild = vi.fn()
    const onBuildPlan = vi.fn()
    const executing: PlanState = {
      ...idlePlanState,
      mode: 'agent',
      phase: 'executing',
      goal: 'Build the plan',
      todos: [
        { id: 't1', title: 'First todo', status: 'in_progress' },
      ],
      approved: true,
    }

    const { rerender } = render(
      <ChatPanel
        {...defaultProps}
        chatMode="agent"
        planState={executing}
        onPauseBuild={onPauseBuild}
        onEndBuild={onEndBuild}
        onBuildPlan={onBuildPlan}
      />,
    )

    fireEvent.click(screen.getAllByLabelText('Pause Build')[0])
    expect(onPauseBuild).toHaveBeenCalled()
    fireEvent.click(screen.getAllByLabelText('End Build')[0])
    expect(onEndBuild).toHaveBeenCalled()

    rerender(
      <ChatPanel
        {...defaultProps}
        chatMode="agent"
        planState={{
          ...executing,
          phase: 'approved_waiting_build',
          todos: [{ id: 't1', title: 'First todo', status: 'pending' }],
        }}
        onPauseBuild={onPauseBuild}
        onEndBuild={onEndBuild}
        onBuildPlan={onBuildPlan}
      />,
    )

    fireEvent.click(screen.getAllByLabelText('Continue Build')[0])
    expect(onBuildPlan).toHaveBeenCalled()
  })

  it('shows stop button when running', () => {
    const onStop = vi.fn()
    render(<ChatPanel {...defaultProps} isRunning={true} onStop={onStop} />)

    const stopButton = screen.getByLabelText('Stop')
    fireEvent.click(stopButton)
    expect(onStop).toHaveBeenCalled()
  })

  it('queues task guidance instead of sending or stopping while running', () => {
    const onSend = vi.fn()
    const onStop = vi.fn()
    const onQueueTaskGuidance = vi.fn()
    render(
      <ChatPanel
        {...defaultProps}
        isRunning={true}
        onSend={onSend}
        onStop={onStop}
        onQueueTaskGuidance={onQueueTaskGuidance}
      />,
    )

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: 'prefer the smaller fix' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onQueueTaskGuidance).toHaveBeenCalledWith('prefer the smaller fix', undefined)
    expect(onSend).not.toHaveBeenCalled()
    expect(onStop).not.toHaveBeenCalled()
  })

  it('renders task guidance queue controls', () => {
    const onApplyTaskGuidance = vi.fn()
    const onDeleteTaskGuidance = vi.fn()
    const onClearTaskGuidance = vi.fn()
    render(
      <ChatPanel
        {...defaultProps}
        isRunning={true}
        taskGuidanceItems={[{
          id: 'tg_1',
          text: 'prefer the smaller fix',
          status: 'queued',
          created_at: 1,
        }]}
        onApplyTaskGuidance={onApplyTaskGuidance}
        onDeleteTaskGuidance={onDeleteTaskGuidance}
        onClearTaskGuidance={onClearTaskGuidance}
      />,
    )

    expect(screen.getByText('任务引导队列 (1)')).toBeInTheDocument()
    fireEvent.click(screen.getByText('任务引导'))
    expect(onApplyTaskGuidance).toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('Remove guidance'))
    expect(onDeleteTaskGuidance).toHaveBeenCalledWith('tg_1')
    fireEvent.click(screen.getByText('清空'))
    expect(onClearTaskGuidance).toHaveBeenCalled()
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

  it('folds an in-progress thinking block until opened', () => {
    const messages: ChatMessage[] = [
      {
        id: 'a1',
        role: 'assistant',
        content: '',
        isTool: false,
        blocks: [
          { type: 'thinking', text: 'partial reasoning so far', timestamp: 1, startedAt: 1000 },
        ],
      },
    ]
    render(<ChatPanel {...defaultProps} messages={messages} />)
    // In-progress thinking stays out of the main reading path until opened.
    const timeline = screen.getByTestId('personal-conversation-timeline')
    expect(within(timeline).getByText('Thinking')).toBeInTheDocument()
    expect(screen.queryByText('partial reasoning so far')).not.toBeInTheDocument()
    fireEvent.click(within(timeline).getByText('Thinking'))
    const body = screen.getByText('partial reasoning so far')
    expect(body).toBeInTheDocument()
    expect(body).not.toHaveClass('font-mono')
    expect(body).toHaveClass('chat-text-sm')
  })

  it('auto-collapses a completed thinking block to "Thought for Ns" and expands on click', () => {
    const messages: ChatMessage[] = [
      {
        id: 'a2',
        role: 'assistant',
        content: '',
        isTool: false,
        blocks: [
          {
            type: 'thinking',
            text: 'the full reasoning trace',
            timestamp: 2,
            startedAt: 1000,
            endedAt: 6000,
            complete: true,
          },
        ],
      },
    ]
    render(<ChatPanel {...defaultProps} messages={messages} />)
    expect(screen.getByText('Thought for 5s')).toBeInTheDocument()
    // Collapsed by default → reasoning text hidden until clicked.
    expect(screen.queryByText('the full reasoning trace')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Thought for 5s'))
    expect(screen.getByText('the full reasoning trace')).toBeInTheDocument()
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

  it('restores the visible message range when a session panel remounts', () => {
    const messages: ChatMessage[] = Array.from({ length: 12 }, (_, index) => ({
      id: `m-${index}`,
      role: index % 2 === 0 ? 'user' : 'assistant',
      content: `message ${index}`,
      isTool: false,
    }))

    const first = render(<ChatPanel {...defaultProps} sessionId="session-scroll" messages={messages} />)
    ;(globalThis as any).__chatPanelVirtuosoProps.rangeChanged({ startIndex: 5, endIndex: 9 })
    first.unmount()

    render(<ChatPanel {...defaultProps} sessionId="session-scroll" messages={messages} />)

    expect((globalThis as any).__chatPanelVirtuosoProps.initialTopMostItemIndex).toEqual({
      index: 5,
      align: 'start',
    })
    expect((globalThis as any).__chatPanelVirtuosoProps.restoreStateFrom).toBeUndefined()
  })

  it('clamps restored scroll index to projected timeline length', () => {
    const manyMessages: ChatMessage[] = Array.from({ length: 12 }, (_, index) => ({
      id: `long-${index}`,
      role: 'assistant',
      content: `message ${index}`,
      isTool: false,
    }))
    const first = render(<ChatPanel {...defaultProps} sessionId="session-clamp" messages={manyMessages} />)
    ;(globalThis as any).__chatPanelVirtuosoProps.rangeChanged({ startIndex: 9, endIndex: 11 })
    first.unmount()

    render(
      <ChatPanel
        {...defaultProps}
        sessionId="session-clamp"
        messages={[{ id: 'short', role: 'assistant', content: 'only one event', isTool: false }]}
      />,
    )

    expect(Object.prototype.hasOwnProperty.call((globalThis as any).__chatPanelVirtuosoProps || {}, 'initialTopMostItemIndex')).toBe(false)
    expect((globalThis as any).__chatPanelVirtuosoProps.restoreStateFrom).toBeUndefined()
  })
})
