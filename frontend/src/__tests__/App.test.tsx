import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

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
    pauseBuild: vi.fn(),
    endBuild: vi.fn(),
    rejectPlan: vi.fn(),
    updatePlanDecision: vi.fn(),
    submitPlanDecisions: vi.fn(),
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
      ;(globalThis as any).__desktopAgentLastSessionViewProps = props;
      const openFile = React.useMemo(() => vi.fn(), [props.sessionId]);
      ;((globalThis as any).__desktopAgentOpenFiles ||= {})[props.sessionId] = openFile;
      React.useImperativeHandle(ref, () => ({ openFile, switchModel: vi.fn(), openRewind: vi.fn() }), [openFile]);
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
    delete (globalThis as any).__desktopAgentLastSessionViewProps
    delete (globalThis as any).__desktopAgentOpenFiles
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

  const collapsedProjectLayout = () => ({
    activeSection: 'project',
    activeAgent: 'personal',
    showTerminal: true,
    rightZone: 'activity',
    rightPanelVisible: false,
    sidebarCollapsed: false,
    mainLayout: { center: 99, right: 1 },
    terminalLayout: { conversation: 76, terminal: 24 },
  })

  const mockProjectFileFetch = (sessionId = 'session_coding_file') => {
    const project = {
      path: 'C:/repo',
      name: 'repo',
      git_branch: 'main',
      last_opened: '2026-05-18T00:00:00Z',
    }
    const nodes = [
      { name: 'src', path: 'src', type: 'dir', has_children: false },
      { name: 'README.md', path: 'README.md', type: 'file', extension: 'md' },
    ]
    return vi.fn((url: string, _init?: RequestInit) => {
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
            providers: { openai: { api_key_configured: true, models: [] } },
            settings: { default_provider: 'openai' },
            personal_agent: { model: 'gpt-4o' },
            coding_agent: { model: 'gpt-4o' },
          }),
        }) as any
      }
      if (url.endsWith('/api/projects/current')) {
        return Promise.resolve({ json: () => Promise.resolve(project) }) as any
      }
      if (url.endsWith('/api/projects/refresh')) {
        return Promise.resolve({ json: () => Promise.resolve({ project, nodes }) }) as any
      }
      if (url.includes('/api/file/read')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ content: '# Hello\n', path: 'C:/repo/README.md' }),
        }) as any
      }
      if (url.endsWith('/api/sessions/resolve')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            session_id: sessionId,
            agent_type: 'coding',
            role_id: 'code-expert',
            model_id: 'gpt-4o',
            title: 'Project',
            project_path: project.path,
            created: false,
            is_primary: false,
          }),
        }) as any
      }
      if (url.endsWith('/api/sessions') || url.includes('/api/sessions?')) {
        return Promise.resolve({ json: () => Promise.resolve({ sessions: [] }) }) as any
      }
      return Promise.resolve({ json: () => Promise.resolve({}) }) as any
    })
  }

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

  it('debounces project refresh after file edits', async () => {
    const project = {
      path: 'C:/repo',
      name: 'repo',
      git_branch: 'main',
      last_opened: '2026-05-18T00:00:00Z',
    }
    const fetchMock = vi.fn((url: string) => {
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
              openai: { api_key_configured: true, models: [] },
            },
            settings: { default_provider: 'openai' },
            personal_agent: { model: 'gpt-4o' },
            coding_agent: { model: 'gpt-4o' },
          }),
        }) as any
      }
      if (url.endsWith('/api/projects/current')) {
        return Promise.resolve({ json: () => Promise.resolve(project) }) as any
      }
      if (url.endsWith('/api/projects/refresh')) {
        return Promise.resolve({
          json: () => Promise.resolve({
            project,
            nodes: [{ name: 'new.ts', path: 'new.ts', type: 'file', extension: 'ts' }],
          }),
        }) as any
      }
      if (url.endsWith('/api/sessions')) {
        return Promise.resolve({ json: () => Promise.resolve({ sessions: [] }) }) as any
      }
      return Promise.resolve({ json: () => Promise.resolve({}) }) as any
    })
    global.fetch = fetchMock as any

    render(<App />)
    await screen.findByText('Desktop Agent')
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/api/projects/refresh'))).toBe(true)
    })
    const initialRefreshCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/projects/refresh')).length

    vi.useFakeTimers()
    try {
      act(() => {
        ;(globalThis as any).__desktopAgentLastSessionViewProps.onProjectFileEdit({
          path: 'C:/repo/new.ts',
          operation: 'create',
          unified_diff: 'diff',
          stats: { added: 1, removed: 0 },
          truncated: false,
        })
        vi.advanceTimersByTime(399)
      })

      expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/projects/refresh')).length).toBe(initialRefreshCalls)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1)
      })

      expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/projects/refresh')).length).toBe(initialRefreshCalls + 1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('loads deep directory children one level at a time', async () => {
    const project = {
      path: 'C:/outer',
      name: 'outer',
      git_branch: 'main',
      last_opened: '2026-05-18T00:00:00Z',
    }
    const rootNodes = [{
      name: 'OPEN AGENT',
      path: 'OPEN AGENT',
      type: 'dir',
      has_children: true,
      children: [{
        name: 'src',
        path: 'OPEN AGENT/src',
        type: 'dir',
        has_children: true,
        children: [{
          name: 'open_agent',
          path: 'OPEN AGENT/src/open_agent',
          type: 'dir',
          has_children: true,
        }],
      }],
    }]
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
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
            providers: { openai: { api_key_configured: true, models: [] } },
            settings: { default_provider: 'openai' },
            personal_agent: { model: 'gpt-4o' },
            coding_agent: { model: 'gpt-4o' },
          }),
        }) as any
      }
      if (url.endsWith('/api/projects/current')) {
        return Promise.resolve({ json: () => Promise.resolve(project) }) as any
      }
      if (url.endsWith('/api/projects/refresh')) {
        return Promise.resolve({ json: () => Promise.resolve({ project, nodes: rootNodes }) }) as any
      }
      if (url.includes('/api/projects/tree?path=OPEN%20AGENT%2Fsrc%2Fopen_agent')) {
        return Promise.resolve({
          json: () => Promise.resolve({
            nodes: [
              { name: 'cli', path: 'OPEN AGENT/src/open_agent/cli', type: 'dir', has_children: false },
              { name: '__init__.py', path: 'OPEN AGENT/src/open_agent/__init__.py', type: 'file', extension: 'py' },
            ],
          }),
        }) as any
      }
      if (url.endsWith('/api/sessions/resolve')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            session_id: 'session_coding_tree',
            agent_type: 'coding',
            role_id: 'code-expert',
            model_id: 'gpt-4o',
            title: 'Tree',
            project_path: project.path,
            created: false,
            is_primary: false,
          }),
        }) as any
      }
      if (url.endsWith('/api/sessions') || url.includes('/api/sessions?')) {
        return Promise.resolve({ json: () => Promise.resolve({ sessions: [] }) }) as any
      }
      return Promise.resolve({ json: () => Promise.resolve({}) }) as any
    })
    global.fetch = fetchMock as any

    render(<App />)
    await screen.findByText('Desktop Agent')
    fireEvent.click(screen.getByLabelText('Coding Agent'))

    fireEvent.click(await screen.findByText('OPEN AGENT'))
    fireEvent.click(await screen.findByText('src'))
    fireEvent.click(await screen.findByText('open_agent'))

    expect(await screen.findByText('cli')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/projects/tree?path=OPEN%20AGENT%2Fsrc%2Fopen_agent'))).toBe(true)
  })

  it('opens a project file in the coding editor and reveals the right panel', async () => {
    localStorage.setItem('desktop-agent-layout', JSON.stringify(collapsedProjectLayout()))
    const fetchMock = mockProjectFileFetch('session_coding_file')
    global.fetch = fetchMock as any

    render(<App />)
    await screen.findByText('Desktop Agent')
    fireEvent.click(screen.getByLabelText('Coding Agent'))
    fireEvent.click(await screen.findByText('README.md'))

    await waitFor(() => {
      expect((globalThis as any).__desktopAgentOpenFiles.session_coding_file).toHaveBeenCalledWith(
        'README.md',
        '# Hello\n',
        'markdown',
      )
    })
    await waitFor(() => {
      const layout = JSON.parse(localStorage.getItem('desktop-agent-layout') || '{}')
      expect(layout.rightPanelVisible).toBe(true)
      expect(layout.rightZone).toBe('workspace')
    })
  })

  it('switches from Personal to Coding before opening a project file', async () => {
    localStorage.setItem('desktop-agent-layout', JSON.stringify(collapsedProjectLayout()))
    const fetchMock = mockProjectFileFetch('session_coding_from_personal')
    global.fetch = fetchMock as any

    render(<App />)
    await screen.findByText('Desktop Agent')
    fireEvent.click(await screen.findByText('README.md'))

    await waitFor(() => {
      const resolveCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/sessions/resolve'))
      expect(resolveCall).toBeTruthy()
      expect(JSON.parse(String(resolveCall?.[1]?.body))).toMatchObject({
        agent_type: 'coding',
        policy: 'last_or_create',
      })
    })
    await waitFor(() => {
      expect((globalThis as any).__desktopAgentOpenFiles.session_coding_from_personal).toHaveBeenCalledWith(
        'README.md',
        '# Hello\n',
        'markdown',
      )
    })
  })

  it('does not open the editor when clicking a directory in the project tree', async () => {
    localStorage.setItem('desktop-agent-layout', JSON.stringify(collapsedProjectLayout()))
    const fetchMock = mockProjectFileFetch('session_coding_file')
    global.fetch = fetchMock as any

    render(<App />)
    await screen.findByText('Desktop Agent')
    fireEvent.click(await screen.findByText('src'))

    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/file/read'))).toBe(false)
    expect((globalThis as any).__desktopAgentOpenFiles?.session_coding_file).toBeUndefined()
  })
})
