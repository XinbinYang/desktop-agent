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
    vi.restoreAllMocks()
    vi.clearAllMocks()
    localStorage.clear()
    delete (globalThis as any).__desktopAgentLastSessionViewProps
    delete (globalThis as any).__desktopAgentOpenFiles
    delete (window as any).electronAPI
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
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
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

  it('creates a new coding session in a split pane without replacing the current pane', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/sessions/resolve')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            session_id: 'session_coding_new',
            agent_type: 'coding',
            role_id: 'code-expert',
            model_id: 'gpt-4o',
            title: 'New Task',
            project_path: null,
            created: true,
            is_primary: false,
          }),
        }) as any
      }
      if (url.endsWith('/api/sessions') || url.includes('/api/sessions?')) {
        return Promise.resolve({ json: () => Promise.resolve({ sessions: [] }) }) as any
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
    await screen.findByTestId('session-session_personal_main')
    fireEvent.click(screen.getByLabelText('Sessions'))
    fireEvent.click(screen.getByRole('button', { name: '/new' }))

    expect(await screen.findByTestId('session-session_coding_new')).toBeInTheDocument()
    expect(screen.getByTestId('session-session_personal_main')).toBeInTheDocument()
    const resolveCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/sessions/resolve'))
    expect(JSON.parse(String(resolveCall?.[1]?.body))).toMatchObject({
      agent_type: 'coding',
      policy: 'new',
    })
  })

  it('opens a session project before switching to a session from that project', async () => {
    const projectA = {
      path: 'C:/repo-a',
      name: 'repo-a',
      git_branch: 'main',
      last_opened: '2026-05-18T00:00:00Z',
    }
    const projectB = {
      path: 'C:/repo-b',
      name: 'repo-b',
      git_branch: 'main',
      last_opened: '2026-05-18T01:00:00Z',
    }
    const history = {
      current_project_path: projectA.path,
      projects: [
        { ...projectA, is_current: true, has_running: false, sessions: [] },
        {
          ...projectB,
          is_current: false,
          has_running: false,
          sessions: [{
            id: 'session_b',
            title: 'Fix bug',
            project_path: projectB.path,
            model_id: 'gpt-4o',
            role_id: 'code-expert',
            agent_type: 'coding',
            message_count: 2,
            updated_at: 1779116000,
            is_primary: false,
            is_running: false,
            active_connections: 0,
            activity_state: 'idle',
          }],
        },
      ],
      standalone_sessions: [],
    }
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
        return Promise.resolve({ json: () => Promise.resolve(projectA) }) as any
      }
      if (url.endsWith('/api/projects/refresh')) {
        return Promise.resolve({ json: () => Promise.resolve({ project: projectA, nodes: [] }) }) as any
      }
      if (url.endsWith('/api/session-history')) {
        return Promise.resolve({ json: () => Promise.resolve(history) }) as any
      }
      if (url.endsWith('/api/projects/open')) {
        expect(JSON.parse(String(init?.body))).toEqual({ path: projectB.path })
        return Promise.resolve({ json: () => Promise.resolve(projectB) }) as any
      }
      if (url.endsWith('/api/projects/tree')) {
        return Promise.resolve({ json: () => Promise.resolve({ nodes: [] }) }) as any
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any
    })
    global.fetch = fetchMock as any

    render(<App />)
    await screen.findByText('Desktop Agent')
    fireEvent.click(screen.getByLabelText('Sessions'))
    fireEvent.click(await screen.findByLabelText('Expand project repo-b'))
    fireEvent.click(await screen.findByLabelText('Open session Fix bug'))

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/api/projects/open'))).toBe(true)
    })
    expect(await screen.findByTestId('session-session_b')).toBeInTheDocument()
  })

  it('handles project action menu through App handlers', async () => {
    const project = {
      path: 'C:/repo',
      name: 'repo',
      git_branch: 'main',
      last_opened: '2026-05-18T00:00:00Z',
    }
    const worktreeProject = {
      path: 'C:/runtime/worktrees/persistent/repo-worktree',
      name: 'repo-worktree',
      git_branch: 'HEAD',
      last_opened: '2026-05-18T01:00:00Z',
    }
    const history = {
      current_project_path: project.path,
      projects: [{
        ...project,
        folder_name: 'repo',
        is_current: true,
        has_running: false,
        is_pinned: false,
        is_archived: false,
        archived_sessions_count: 0,
        source: 'recent',
        sessions: [],
      }],
      standalone_sessions: [],
    }
    const revealPath = vi.fn(() => Promise.resolve('reveal failed'))
    const openPath = vi.fn(() => Promise.resolve(null))
    ;(window as any).electronAPI = { revealPath, openPath }
    const promptSpy = vi.spyOn(window, 'prompt')
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
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
        return Promise.resolve({ json: () => Promise.resolve({ project, nodes: [] }) }) as any
      }
      if (url.endsWith('/api/projects/tree')) {
        return Promise.resolve({ json: () => Promise.resolve({ nodes: [] }) }) as any
      }
      if (url.endsWith('/api/session-history')) {
        return Promise.resolve({ json: () => Promise.resolve(history) }) as any
      }
      if (url.endsWith('/api/projects/history/pin')) {
        return Promise.resolve({ json: () => Promise.resolve({ status: 'ok', project: {} }) }) as any
      }
      if (url.endsWith('/api/projects/history/rename')) {
        return Promise.resolve({ json: () => Promise.resolve({ status: 'ok', project: {} }) }) as any
      }
      if (url.endsWith('/api/projects/history/archive-sessions')) {
        return Promise.resolve({ json: () => Promise.resolve({ status: 'ok', archived_sessions: 2 }) }) as any
      }
      if (url.endsWith('/api/projects/history/remove')) {
        return Promise.resolve({ json: () => Promise.resolve({ status: 'ok', archived_sessions: 2 }) }) as any
      }
      if (url.endsWith('/api/projects/worktrees/persistent')) {
        return Promise.resolve({
          json: () => Promise.resolve({ status: 'ok', path: worktreeProject.path, project: worktreeProject }),
        }) as any
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any
    })
    global.fetch = fetchMock as any

    render(<App />)
    await screen.findByText('Desktop Agent')
    fireEvent.click(screen.getByLabelText('Sessions'))
    await screen.findByText('repo')

    fireEvent.click(screen.getByLabelText('Project actions for repo'))
    fireEvent.click(await screen.findByText('在资源管理器中打开'))
    await waitFor(() => {
      expect(revealPath).toHaveBeenCalledWith(project.path)
      expect(openPath).toHaveBeenCalledWith(project.path)
    })

    fireEvent.click(screen.getByLabelText('Project actions for repo'))
    fireEvent.click(await screen.findByText('置顶项目'))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/projects/history/pin'))
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ path: project.path, pinned: true })
    })

    promptSpy.mockReturnValueOnce('Repo Alias')
    fireEvent.click(screen.getByLabelText('Project actions for repo'))
    fireEvent.click(await screen.findByText('重命名项目'))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/projects/history/rename'))
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ path: project.path, name: 'Repo Alias' })
    })

    fireEvent.click(screen.getByLabelText('Project actions for repo'))
    fireEvent.click(await screen.findByText('归档对话'))
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled()
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/api/projects/history/archive-sessions'))).toBe(true)
    })

    fireEvent.click(screen.getByLabelText('Project actions for repo'))
    fireEvent.click(await screen.findByText('移除'))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/api/projects/history/remove'))).toBe(true)
    })

    promptSpy.mockReturnValueOnce('repo-worktree')
    fireEvent.click(screen.getByLabelText('Project actions for repo'))
    fireEvent.click(await screen.findByText('创建永久工作树'))
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/projects/worktrees/persistent'))
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ path: project.path, name: 'repo-worktree' })
    })
  })

  it('stops only the closed pane session and keeps sibling panes mounted', async () => {
    localStorage.setItem('desktop-agent-pane-tree', JSON.stringify({
      version: 2,
      focusedLeafId: 'leaf_a',
      paneRoot: {
        type: 'split',
        id: 'root',
        direction: 'horizontal',
        sizes: [50, 50],
        children: [
          {
            type: 'leaf',
            id: 'leaf_a',
            pane: { id: 'pane_a', sessionId: 'session_a', model: 'gpt-4o', agentType: 'coding', role: 'code-expert' },
          },
          {
            type: 'leaf',
            id: 'leaf_b',
            pane: { id: 'pane_b', sessionId: 'session_b', model: 'gpt-4o', agentType: 'coding', role: 'code-expert' },
          },
        ],
      },
    }))
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/sessions/session_b/stop')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'ok', was_running: true }) }) as any
      }
      if (url.endsWith('/api/sessions') || url.includes('/api/sessions?')) {
        return Promise.resolve({ json: () => Promise.resolve({ sessions: [] }) }) as any
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
    await screen.findByTestId('session-session_a')
    fireEvent.click(screen.getAllByLabelText('Close pane')[1])

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) =>
        String(url).endsWith('/api/sessions/session_b/stop') &&
        (init as RequestInit | undefined)?.method === 'POST',
      )).toBe(true)
    })
    expect(screen.getByTestId('session-session_a')).toBeInTheDocument()
    expect(screen.queryByTestId('session-session_b')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/api/sessions/session_a/stop'))).toBe(false)
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

  it('runs a project file from the file tree context menu', async () => {
    localStorage.setItem('desktop-agent-layout', JSON.stringify(collapsedProjectLayout()))
    const project = {
      path: 'C:/repo',
      name: 'repo',
      git_branch: 'main',
      last_opened: '2026-05-18T00:00:00Z',
    }
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
        return Promise.resolve({
          json: () => Promise.resolve({
            project,
            nodes: [{ name: 'script.py', path: 'script.py', type: 'file', extension: 'py' }],
          }),
        }) as any
      }
      if (url.endsWith('/api/projects/actions/run')) {
        return Promise.resolve({
          json: () => Promise.resolve({
            status: 'ok',
            command: 'python script.py',
            output: 'done',
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
    fireEvent.contextMenu(await screen.findByText('script.py'))
    fireEvent.click(await screen.findByText('运行文件'))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/projects/actions/run'))
      expect(call).toBeTruthy()
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ path: 'script.py', action: 'run_file' })
    })
  })
})
