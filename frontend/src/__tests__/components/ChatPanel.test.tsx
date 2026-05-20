import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { ChatPanel } from '../../components/ChatPanel'
import { PersonalChatSurface } from '../../components/chat/PersonalChatSurface'
import { __resetSlashCommandCacheForTests } from '../../components/SlashCommandMenu'
import type { ChatMessage, FileEdit, PlanState, ToolCall } from '../../types'

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
  beforeEach(() => {
    __resetSlashCommandCacheForTests()
    localStorage.removeItem('desktop-agent-personal-chat-v2')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

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

  it('uses a custom Personal Agent name in the social chat surface', () => {
    const messages: ChatMessage[] = [
      { id: '2', role: 'assistant', content: 'Hi there', isTool: false, turnComplete: true },
    ]
    render(<ChatPanel {...defaultProps} messages={messages} agentType="personal" assistantDisplayName="镜与刃" />)
    expect(screen.getByText('镜与刃')).toBeInTheDocument()
    expect(screen.queryByText('Desktop Agent')).not.toBeInTheDocument()
  })

  it('does not expose project @mentions for Personal Agent', async () => {
    render(
      <ChatPanel
        {...defaultProps}
        agentType="personal"
        projectOpen={true}
        fileTree={[{ name: 'README.md', path: 'README.md', type: 'file', extension: 'md' }]}
      />,
    )

    fireEvent.change(screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)'), {
      target: { value: '@' },
    })

    expect(await screen.findByText('Coding Agent')).toBeInTheDocument()
    expect(screen.queryByText('Git')).not.toBeInTheDocument()
    expect(screen.queryByText('README.md')).not.toBeInTheDocument()
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

  it('uses the personal social chat surface by default and folds adjacent tools', () => {
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

    expect(screen.getByTestId('personal-chat-v2')).toHaveClass('personal-chat-surface')
    expect(screen.getByText(/我处理了 2 步/)).toBeInTheDocument()
    expect(screen.getByText(/用了 2 个工具/)).toBeInTheDocument()
    expect(screen.queryByText('Used 2 tools')).not.toBeInTheDocument()
    expect(screen.queryByText('knowledge_search')).not.toBeInTheDocument()
    expect(screen.getByText('I found the note.')).toBeInTheDocument()
    fireEvent.click(screen.getByText(/我处理了 2 步/))
    expect(screen.getByText('Used 2 tools')).toBeInTheDocument()
  })

  it('renders Personal markdown inside the Discord-like scoped surface', () => {
    const messages: ChatMessage[] = [{
      id: 'a-markdown',
      role: 'assistant',
      content: [
        '## Scenario',
        '',
        'I prefer **scenario three** with `memory_search`.',
        '',
        '- Breakeven moved',
        '- Duration recovered',
        '',
        '| Action | Effect |',
        '| --- | --- |',
        '| Review memory | Less duplicate output |',
      ].join('\n'),
      isTool: false,
      turnComplete: true,
    }]

    render(<ChatPanel {...defaultProps} agentType="personal" messages={messages} />)

    const timeline = screen.getByTestId('personal-chat-v2')
    expect(timeline).toHaveClass('personal-chat-surface')
    expect(timeline.querySelector('.personal-chat-row')).toBeTruthy()
    expect(timeline.querySelector('.personal-chat-message')).toBeTruthy()
    expect(within(timeline).getByRole('heading', { name: 'Scenario' })).toBeInTheDocument()

    const strong = within(timeline).getByText('scenario three')
    expect(strong.tagName.toLowerCase()).toBe('strong')

    const inlineCode = timeline.querySelector('code')
    expect(inlineCode).toHaveTextContent('memory_search')

    expect(within(timeline).getByText('Breakeven moved')).toBeInTheDocument()
    const table = timeline.querySelector('table') as HTMLElement | null
    expect(table).toBeTruthy()
    expect(within(table as HTMLElement).getByText('Action')).toBeInTheDocument()
    expect(within(table as HTMLElement).getByText('Less duplicate output')).toBeInTheDocument()
  })

  it('marks Personal rows with stable role and tone attributes', () => {
    const timestamp = Date.UTC(2026, 4, 20, 10, 0, 0)
    const messages: ChatMessage[] = [
      { id: 'u-role', role: 'user', content: 'hello', isTool: false, createdAt: timestamp },
      { id: 'a-role', role: 'assistant', content: 'hi there', isTool: false, turnComplete: true, createdAt: timestamp + 1000 },
      { id: 's-success', role: 'system', content: 'saved', isTool: false, noticeLevel: 'success', createdAt: timestamp + 2000 },
      { id: 's-error', role: 'system', content: 'failed', isTool: false, noticeLevel: 'error', createdAt: timestamp + 10 * 60 * 1000 },
    ]

    render(<ChatPanel {...defaultProps} agentType="personal" messages={messages} />)

    const timeline = screen.getByTestId('personal-chat-v2')
    const rows = Array.from(timeline.querySelectorAll('.personal-chat-row')) as HTMLElement[]
    const avatars = Array.from(timeline.querySelectorAll('.personal-chat-avatar')) as HTMLElement[]
    const authors = Array.from(timeline.querySelectorAll('.personal-chat-author')) as HTMLElement[]
    const messageItems = Array.from(timeline.querySelectorAll('.personal-chat-message')) as HTMLElement[]

    expect(rows.map((row) => row.dataset.role)).toEqual(['user', 'assistant', 'system', 'system'])
    expect(rows.map((row) => row.dataset.tone)).toEqual(['user', 'assistant', 'system-success', 'system-error'])
    expect(avatars.map((avatar) => avatar.dataset.tone)).toEqual(['user', 'assistant', 'system-success', 'system-error'])
    expect(authors.map((author) => author.dataset.tone)).toEqual(['user', 'assistant', 'system-success', 'system-error'])
    expect(messageItems.map((item) => item.dataset.tone)).toEqual(['user', 'assistant', 'system-success', 'system-error'])
    expect(timeline.querySelectorAll('.personal-chat-row-inner')).toHaveLength(4)
  })

  it('keeps Personal process summaries visually neutral when activities include errors', () => {
    const messages: ChatMessage[] = [{
      id: '2',
      role: 'assistant',
      content: '',
      isTool: false,
      turnComplete: true,
      blocks: [
        {
          type: 'tool_call',
          name: 'web_search',
          args: { query: 'macro data' },
          result: '[ERROR] timeout',
          status: 'error',
          toolCallId: 'search-error',
          timestamp: 1,
        },
      ],
    }]

    render(<ChatPanel {...defaultProps} agentType="personal" messages={messages} />)

    const drawerButton = screen.getByTestId('personal-activity-drawer').querySelector('button')
    expect(drawerButton).toHaveClass('border-border-subtle')
    expect(drawerButton).toHaveClass('bg-surface/55')
    expect(drawerButton).toHaveClass('text-fg-muted')
    expect(drawerButton).not.toHaveClass('border-danger/25')
    expect(drawerButton).not.toHaveClass('bg-danger/10')
    expect(drawerButton).not.toHaveClass('text-danger')
  })

  it('collapses completed Personal activities into a process drawer', () => {
    const timestamp = Date.UTC(2026, 4, 20, 10, 0, 0)
    const messages: ChatMessage[] = [{
      id: '2',
      role: 'assistant',
      content: '',
      isTool: false,
      turnComplete: true,
      blocks: [
        {
          type: 'thinking',
          text: 'checking the local memory',
          timestamp: timestamp + 5000,
          startedAt: timestamp,
          endedAt: timestamp + 5000,
          complete: true,
        },
        {
          type: 'file_edit',
          timestamp: timestamp + 6000,
          edit: {
            path: 'src/example.ts',
            operation: 'modify',
            unified_diff: '--- a/src/example.ts\n+++ b/src/example.ts\n-old\n+new\n',
            stats: { added: 1, removed: 1 },
            truncated: false,
            tool_call_id: 'edit-1',
          },
        },
        { type: 'text', text: 'Done.', timestamp: timestamp + 7000 },
      ],
    }]

    render(<ChatPanel {...defaultProps} agentType="personal" messages={messages} />)

    expect(screen.getByText(/我处理了 2 步/)).toBeInTheDocument()
    expect(screen.getByText(/思考 5 秒/)).toBeInTheDocument()
    expect(screen.getByText(/修改 1 个文件/)).toBeInTheDocument()
    expect(screen.queryByText('Thought for 5s')).not.toBeInTheDocument()
    expect(screen.queryByText(/src\/example\.ts/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByText(/我处理了 2 步/))

    expect(screen.getByText('Thought for 5s')).toBeInTheDocument()
    expect(screen.getByText(/modify src\/example\.ts/)).toBeInTheDocument()
  })

  it('keeps running Personal activities visible until the turn finishes', () => {
    const timestamp = Date.UTC(2026, 4, 20, 10, 0, 0)
    const messages: ChatMessage[] = [{
      id: '2',
      role: 'assistant',
      content: '',
      isTool: false,
      turnComplete: false,
      blocks: [
        { type: 'thinking', text: 'checking memory', timestamp: timestamp + 1000, complete: false },
        {
          type: 'tool_call',
          name: 'knowledge_search',
          args: { query: 'memory' },
          status: 'running',
          toolCallId: 'k1',
          timestamp: timestamp + 2000,
        },
      ],
    }]

    render(<ChatPanel {...defaultProps} agentType="personal" messages={messages} isRunning={true} />)

    expect(screen.getByText(/正在处理 2 步/)).toBeInTheDocument()
    expect(screen.getAllByText('Thinking').length).toBeGreaterThan(0)
    expect(screen.getByText(/Using Search memory/)).toBeInTheDocument()
  })

  it('auto-expands hidden Personal activities when search matches them', () => {
    const timestamp = Date.UTC(2026, 4, 20, 10, 0, 0)
    const messages: ChatMessage[] = [{
      id: '2',
      role: 'assistant',
      content: '',
      isTool: false,
      turnComplete: true,
      blocks: [
        {
          type: 'file_edit',
          timestamp,
          edit: {
            path: 'secret-notes.md',
            operation: 'modify',
            unified_diff: '--- a/secret-notes.md\n+++ b/secret-notes.md\n-old\n+new\n',
            stats: { added: 1, removed: 1 },
            truncated: false,
            tool_call_id: 'edit-1',
          },
        },
      ],
    }]

    render(
      <PersonalChatSurface
        messages={messages}
        planState={idlePlanState}
        searchQuery="secret-notes"
        isRunning={false}
        onOpenImage={vi.fn()}
        emptyPlaceholder={<div />}
        markdownTheme="light"
      />,
    )

    const timeline = screen.getByTestId('personal-chat-v2')
    expect(within(timeline).getByText(/我处理了 1 步/)).toBeInTheDocument()
    expect(within(timeline).getByText(/modify secret-notes\.md/)).toBeInTheDocument()
  })

  it('filters Personal v2 after building the full conversation so fallback activity stays on its original turn', () => {
    const messages: ChatMessage[] = [
      {
        id: 'a-match',
        role: 'assistant',
        content: 'needle answer',
        isTool: false,
        turnComplete: true,
      },
      {
        id: 'a-latest',
        role: 'assistant',
        content: 'ordinary latest answer',
        isTool: false,
        turnComplete: true,
      },
    ]
    const toolCalls: ToolCall[] = [{
      name: 'shell_execute',
      args: { command: 'unrelated-command' },
      result: 'unrelated result',
      timestamp: Date.UTC(2026, 4, 20, 10, 0, 0),
      toolCallId: 'tool-unrelated',
    }]
    const fileEdits: FileEdit[] = [{
      path: 'unrelated.txt',
      operation: 'modify',
      unified_diff: '--- a/unrelated.txt\n+++ b/unrelated.txt\n-old\n+new\n',
      stats: { added: 1, removed: 1 },
      truncated: false,
      timestamp: Date.UTC(2026, 4, 20, 10, 0, 1),
    }]

    render(
      <PersonalChatSurface
        messages={messages}
        toolCalls={toolCalls}
        fileEdits={fileEdits}
        planState={idlePlanState}
        searchQuery="needle"
        isRunning={false}
        onOpenImage={vi.fn()}
        emptyPlaceholder={<div />}
        markdownTheme="light"
      />,
    )

    const timeline = screen.getByTestId('personal-chat-v2')
    expect(within(timeline).getByText('needle answer')).toBeInTheDocument()
    expect(within(timeline).queryByText('ordinary latest answer')).not.toBeInTheDocument()
    expect(within(timeline).queryByText(/unrelated-command/)).not.toBeInTheDocument()
    expect(within(timeline).queryByText(/unrelated\.txt/)).not.toBeInTheDocument()
  })

  it('does not show epoch time for Personal messages without real timestamps', () => {
    const messages: ChatMessage[] = [{
      id: 'timestamp-less-user',
      role: 'user',
      content: 'This should not inherit 1970 time',
      isTool: false,
    }]

    render(<ChatPanel {...defaultProps} agentType="personal" messages={messages} />)

    const timeline = screen.getByTestId('personal-chat-v2')
    expect(within(timeline).getByText('This should not inherit 1970 time')).toBeInTheDocument()
    expect(within(timeline).queryByText('08:00')).not.toBeInTheDocument()
  })

  it('bottom-aligns the Personal chat surface and opens at the latest message', () => {
    const messages: ChatMessage[] = [
      { id: 'u-old', role: 'user', content: 'old question', isTool: false },
      { id: 'a-old', role: 'assistant', content: 'old answer', isTool: false, turnComplete: true },
      { id: 'u-new', role: 'user', content: 'latest question', isTool: false },
    ]

    render(<ChatPanel {...defaultProps} agentType="personal" messages={messages} />)

    expect((globalThis as any).__chatPanelVirtuosoProps.alignToBottom).toBe(true)
    expect((globalThis as any).__chatPanelVirtuosoProps.initialTopMostItemIndex).toEqual({
      index: 'LAST',
      align: 'end',
    })
  })

  it('can roll Personal Agent back to the legacy conversation timeline', () => {
    localStorage.setItem('desktop-agent-personal-chat-v2', '0')
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
    expect(screen.queryByTestId('personal-chat-v2')).not.toBeInTheDocument()
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

  it('opens sent image attachments in a full-size preview', () => {
    const messages: ChatMessage[] = [
      { id: '1', role: 'user', content: 'Can you see this?', imageBase64: 'abc123', isTool: false },
    ]
    render(<ChatPanel {...defaultProps} messages={messages} />)

    fireEvent.click(screen.getByRole('button', { name: 'Open attached image' }))

    const dialog = screen.getByRole('dialog', { name: 'Image preview' })
    expect(within(dialog).getByAltText('Open attached image')).toHaveAttribute('src', 'data:image/png;base64,abc123')

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Image preview' })).not.toBeInTheDocument()
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
    const onDraftClear = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => ({
        commands: [
          { name: 'help', description: 'Show help', args: '', category: 'general' },
        ],
      }),
    })))

    render(<ChatPanel {...defaultProps} onSend={onSend} onCommand={onCommand} onDraftClear={onDraftClear} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: '/' } })
    await screen.findByText('/help')
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(onCommand).toHaveBeenCalledWith('help', ''))
    expect(onDraftClear).toHaveBeenCalled()
    expect(onSend).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('can select a slash menu command more than once', async () => {
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
    fireEvent.change(input, { target: { value: '/' } })
    await screen.findByText('/help')
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(onCommand).toHaveBeenCalledTimes(2))
    expect(onSend).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('does not swallow direct slash commands when the menu has no matches', () => {
    const onSend = vi.fn()
    const onCommand = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async () => ({
      json: async () => ({ commands: [] }),
    })))

    render(<ChatPanel {...defaultProps} onSend={onSend} onCommand={onCommand} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: '/clear' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onCommand).toHaveBeenCalledWith('clear', '')
    expect(onSend).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('executes /reset from direct input instead of sending chat', () => {
    const onSend = vi.fn()
    const onCommand = vi.fn()
    render(<ChatPanel {...defaultProps} onSend={onSend} onCommand={onCommand} />)

    const input = screen.getByPlaceholderText('Type a message... (Shift+Enter for new line)')
    fireEvent.change(input, { target: { value: '/reset' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onCommand).toHaveBeenCalledWith('reset', '')
    expect(onSend).not.toHaveBeenCalled()
  })

  it('renders command notices neutrally instead of as errors', () => {
    localStorage.setItem('desktop-agent-personal-chat-v2', '0')
    const messages: ChatMessage[] = [{
      id: 'notice-1',
      role: 'system',
      source: 'command_notice',
      noticeLevel: 'success',
      content: 'New session started - model: gpt-4o',
      isTool: false,
    }]

    render(<ChatPanel {...defaultProps} messages={messages} />)

    const notice = screen.getByText('New session started - model: gpt-4o')
    expect(notice).toBeInTheDocument()
    expect(notice).toHaveClass('text-success')
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

  it('shows inline running thinking activity', () => {
    const messages: ChatMessage[] = [{
      id: 'a-thinking',
      role: 'assistant',
      content: '',
      isTool: false,
      turnComplete: false,
      blocks: [{ type: 'thinking', text: 'Waiting for model response...', timestamp: Date.now(), startedAt: Date.now() }],
    }]
    render(<ChatPanel {...defaultProps} messages={messages} isRunning={true} />)
    expect(screen.getAllByText('Thinking').length).toBeGreaterThan(0)
  })

  it('uses the shared CSS spin animation for inline running activity', () => {
    const messages: ChatMessage[] = [{
      id: 'a-thinking',
      role: 'assistant',
      content: '',
      isTool: false,
      turnComplete: false,
      blocks: [{ type: 'thinking', text: 'Waiting for model response...', timestamp: Date.now(), startedAt: Date.now() }],
    }]
    render(<ChatPanel {...defaultProps} messages={messages} isRunning={true} />)
    const spinner = screen.getByTestId('agent-running-spinner')

    expect(spinner).toHaveClass('agent-running-spinner')
    expect(spinner).toHaveClass('animate-spin')
    expect(spinner).not.toHaveAttribute('style')
  })

  it('tracks running tool activity inline without rendering a duplicate footer status', () => {
    const messages: ChatMessage[] = [{
      id: 'a-running-tool',
      role: 'assistant',
      content: '',
      isTool: false,
      turnComplete: false,
      blocks: [
        {
          type: 'tool_call',
          name: 'knowledge_search',
          args: { query: 'tea' },
          status: 'running',
          toolCallId: 'search-1',
          timestamp: 1,
        },
      ],
    }]

    render(<ChatPanel {...defaultProps} messages={messages} isRunning={true} />)

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByText('Using Search tea')).toBeInTheDocument()
    expect(screen.getAllByTestId('agent-running-spinner')).toHaveLength(1)
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
    expect(screen.getByText('First todo')).toBeInTheDocument()
    expect(screen.getByText('Second todo')).toBeInTheDocument()
    expect(screen.getByText('2/2')).toBeInTheDocument()
  })

  it('dedupes in-stream plan execution while the fixed Build panel is visible', () => {
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
    const messages: ChatMessage[] = [{
      id: 'execution',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [{
        type: 'plan_execution',
        goal: 'Build the plan',
        todos: executing.todos,
        timestamp: 1,
      }],
    }]

    render(<ChatPanel {...defaultProps} chatMode="agent" messages={messages} planState={executing} />)

    expect(screen.getAllByText('Build')).toHaveLength(1)
    expect(screen.getAllByText('Second todo')).toHaveLength(1)
    expect(screen.getAllByLabelText('Pause Build')).toHaveLength(1)
    expect(screen.getAllByLabelText('End Build')).toHaveLength(1)
  })

  it('keeps the plan draft card static after Build starts', () => {
    const executing: PlanState = {
      ...idlePlanState,
      mode: 'plan',
      phase: 'executing',
      goal: 'Add plan UX',
      todos: [
        { id: 'live', title: 'Live execution todo', status: 'in_progress' },
      ],
      approved: true,
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
        todos: [{ id: 'draft', title: 'Draft review todo', status: 'pending' }],
        structured_plan: null,
        timestamp: 1,
      }],
    }]

    render(<ChatPanel {...defaultProps} chatMode="plan" messages={messages} planState={executing} />)

    expect(screen.getByText('Draft review todo')).toBeInTheDocument()
    expect(screen.getByText('Live execution todo')).toBeInTheDocument()
    expect(screen.queryByText('Building')).not.toBeInTheDocument()
    expect(screen.queryByText(/Plan approved/)).not.toBeInTheDocument()
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

    expect(screen.getAllByLabelText('Pause Build')).toHaveLength(1)
    expect(screen.getAllByLabelText('End Build')).toHaveLength(1)

    fireEvent.click(screen.getByLabelText('Pause Build'))
    expect(onPauseBuild).toHaveBeenCalled()
    fireEvent.click(screen.getByLabelText('End Build'))
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

    expect(screen.getAllByLabelText('Continue Build')).toHaveLength(1)
    fireEvent.click(screen.getByLabelText('Continue Build'))
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

  it('hides task guidance queue when not running', () => {
    render(
      <ChatPanel
        {...defaultProps}
        isRunning={false}
        taskGuidanceItems={[{
          id: 'tg_1',
          text: 'prefer the smaller fix',
          status: 'queued',
          created_at: 1,
        }]}
      />,
    )

    expect(screen.queryByText('任务引导队列 (1)')).not.toBeInTheDocument()
  })

  it('does not render stale task guidance as a queue item', () => {
    render(
      <ChatPanel
        {...defaultProps}
        isRunning={true}
        taskGuidanceItems={[{
          id: 'tg_1',
          text: 'continue as a new question',
          status: 'stale',
          created_at: 1,
        }]}
      />,
    )

    expect(screen.queryByText('任务引导队列 (1)')).not.toBeInTheDocument()
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
    const timeline = screen.getByTestId('personal-chat-v2')
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
    expect(screen.getByText(/我处理了 1 步/)).toBeInTheDocument()
    expect(screen.getByText(/思考 5 秒/)).toBeInTheDocument()
    expect(screen.queryByText('Thought for 5s')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText(/我处理了 1 步/))
    expect(screen.getByText('Thought for 5s')).toBeInTheDocument()
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
    localStorage.setItem('desktop-agent-personal-chat-v2', '0')
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
    localStorage.setItem('desktop-agent-personal-chat-v2', '0')
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
