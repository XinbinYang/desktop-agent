import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

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

vi.mock('../components/session/SessionView', async () => {
  const React = await import('react');
  const actions = {
    sendMessage: vi.fn(),
    clearSession: vi.fn(),
    compactSession: vi.fn(),
    loadCheckpoints: vi.fn(async () => []),
    rewindToCheckpoint: vi.fn(),
    stopRunning: vi.fn(),
    retryLast: vi.fn(),
    switchModel: vi.fn(),
    executeToolDirect: vi.fn(),
    addTerminalLog: vi.fn(),
    approvePlan: vi.fn(),
    buildPlan: vi.fn(),
    rejectPlan: vi.fn(),
    updatePlanDecision: vi.fn(),
    onSelectFileInEditor: vi.fn(),
    onCloseFileInEditor: vi.fn(),
    onFileContentChange: vi.fn(),
    onSaveFile: vi.fn(),
    saveInputDraft: vi.fn(async () => undefined),
    loadInputDraft: vi.fn(async () => undefined),
    clearInputDraft: vi.fn(async () => undefined),
    runAction: vi.fn(async () => undefined),
    openRunWorktree: vi.fn(async () => undefined),
    handleOpenFileFromPanel: vi.fn(),
    handleOpenFileFromPanelWithLine: vi.fn(),
  };
  return {
    SessionView: React.forwardRef((props: any, ref: any) => {
      React.useImperativeHandle(ref, () => ({ openFile: vi.fn(), switchModel: vi.fn(), openRewind: vi.fn() }));
      React.useEffect(() => {
        props.onSnapshot({
          sessionId: props.sessionId,
          agentType: props.agentType,
          isRunning: false,
          isConnected: false,
          chatMode: 'agent',
          thinkingIntensity: 'medium',
          planState: { mode: 'agent', phase: 'idle', goal: '', draft: '', questions: [], todos: [], decisions: {}, approved: false },
          contextUsage: null,
          checkpoints: [],
          artifacts: [],
          editorGroups: [{ id: 'main', activeFileId: null, openFiles: [] }],
          activeEditorGroup: 'main',
          latestToolCall: null,
          fileEdits: [],
          toolCalls: [],
          runEvents: [],
        }, actions);
      }, [props.sessionId, props.agentType, props.onSnapshot]);
      return <div data-testid={`session-${props.sessionId}`}>{props.sessionId}</div>;
    }),
  };
});

import App from '../App'

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    // Reset fetch mock
    global.fetch = vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({
          models: [
            { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
          ],
          default: 'gpt-4o',
        }),
      })
    ) as any
  })

  it('renders without crashing', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Desktop Agent')).toBeInTheDocument()
    })
  })

  it('fetches models on mount', async () => {
    render(<App />)
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('http://127.0.0.1:8765/api/models')
    })
  })

  it('shows connection status', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Desktop Agent')).toBeInTheDocument()
    })
    // Initially disconnected until WS connects
    expect(screen.getByText('○ Ready')).toBeInTheDocument()
  })
  it('resolves a coding session when clicking Coding Agent', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/sessions/resolve')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            session_id: 'session_coding_1',
            agent_type: 'coding',
            role_id: 'code-expert',
            model_id: 'gpt-4o',
            title: 'Implement tabs',
            project_path: null,
            created: true,
            is_primary: false,
          }),
        }) as any
      }
      if (url.endsWith('/api/sessions')) {
        return Promise.resolve({ json: () => Promise.resolve({ sessions: [] }) }) as any
      }
      if (url.endsWith('/api/settings')) {
        return Promise.resolve({
          json: () => Promise.resolve({
            providers: {
              openai: {
                api_key_configured: true,
                models: [],
              },
            },
            settings: { default_provider: 'openai' },
            personal_agent: { model: 'gpt-4o' },
            coding_agent: { model: 'gpt-4o' },
          }),
        }) as any
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          models: [
            { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
          ],
          default: 'gpt-4o',
        }),
      }) as any
    })
    global.fetch = fetchMock as any

    render(<App />)
    await screen.findByText('Desktop Agent')

    fireEvent.click(screen.getByLabelText('Coding Agent'))

    await waitFor(() => {
      const resolveCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/sessions/resolve'))
      expect(resolveCall).toBeTruthy()
      expect(JSON.parse(String(resolveCall?.[1]?.body))).toMatchObject({
        agent_type: 'coding',
        policy: 'last_or_create',
      })
    })
    expect(await screen.findByTitle('Coding Agent · Implement tabs')).toBeInTheDocument()
  })

  it('opens settings when the default provider has no configured API key', async () => {
    global.fetch = vi.fn((url: string) => {
      if (url.endsWith('/api/models')) {
        return Promise.resolve({
          json: () => Promise.resolve({
            models: [
              { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
            ],
            default: 'gpt-4o',
          }),
        }) as any
      }
      if (url.endsWith('/api/settings')) {
        return Promise.resolve({
          json: () => Promise.resolve({
            providers: {
              openai: {
                name: 'openai',
                base_url: 'https://api.openai.com/v1',
                api_key_masked: '${OPENAI_API_KEY}',
                api_key_configured: false,
                models: [
                  { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', vision: true, context: 128000 },
                ],
              },
            },
            settings: {
              default_model: 'gpt-4o',
              default_provider: 'openai',
              max_iterations: 50,
              auto_approve: false,
              screenshot_on_step: true,
            },
          }),
        }) as any
      }
      if (url.endsWith('/api/roles')) {
        return Promise.resolve({ json: () => Promise.resolve({ roles: [] }) }) as any
      }
      if (url.endsWith('/api/sessions')) {
        return Promise.resolve({ json: () => Promise.resolve({ sessions: [] }) }) as any
      }
      return Promise.resolve({ json: () => Promise.resolve({}) }) as any
    }) as any

    render(<App />)

    expect(await screen.findByText('Providers')).toBeInTheDocument()
  })
})
