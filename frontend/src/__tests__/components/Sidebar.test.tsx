import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { Sidebar } from '../../components/Sidebar'

describe('Sidebar', () => {
  const defaultProps = {
    activeSection: 'skills' as const,
    activeAgent: 'personal' as const,
    onSectionChange: vi.fn(),
    agentModel: 'gpt-4o',
    onOpenPersonalWorkspace: vi.fn(),
    onOpenSettings: vi.fn(),
    onClear: vi.fn(),
    onExecuteTool: vi.fn(),
    isConnected: true,
  }

  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({
        skills: [
          {
            id: 'using-superpowers',
            name: 'using-superpowers',
            description: 'Load relevant skills only when needed.',
            source: 'superpowers',
            enabledByAgent: { personal: true, coding: true },
            recommendedFor: ['personal', 'coding'],
            category: 'workflow',
            trustLevel: 'local',
          },
          {
            id: 'test-driven-development',
            name: 'test-driven-development',
            description: 'Write tests before implementation.',
            source: 'superpowers',
            enabledByAgent: { personal: false, coding: true },
            recommendedFor: ['coding'],
            category: 'workflow',
            trustLevel: 'local',
          },
          {
            id: 'personal:data_analysis',
            name: 'Data Analysis',
            description: 'Personal data analysis preference.',
            source: 'personal',
            enabledByAgent: { personal: true, coding: false },
            recommendedFor: ['personal'],
            category: 'personal',
            trustLevel: 'local',
          },
        ],
        preferences: {
          personal: {
            'using-superpowers': true,
            'test-driven-development': false,
            'personal:data_analysis': true,
          },
          coding: {
            'using-superpowers': true,
            'test-driven-development': true,
            'personal:data_analysis': false,
          },
        },
        defaults: { personal: {}, coding: {} },
        presets: [
          {
            id: 'personal-daily',
            name: 'Personal Daily',
            description: 'Personal task defaults.',
            agentTypes: ['personal'],
            skillIds: ['using-superpowers', 'personal:data_analysis'],
          },
          {
            id: 'debug-fix',
            name: 'Debug Fix',
            description: 'Debug and verify.',
            agentTypes: ['coding'],
            skillIds: ['test-driven-development'],
          },
        ],
      }),
    })))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders skills catalog instead of quick tools', async () => {
    render(<Sidebar {...defaultProps} />)
    expect(await screen.findByText('Core')).toBeInTheDocument()
    expect(screen.queryByText('using-superpowers')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Expand Core'))
    expect(screen.getByText('using-superpowers')).toBeInTheDocument()
    expect(screen.getByText('Quality & Review')).toBeInTheDocument()
    expect(screen.getByLabelText('Disable all Personal for Personal Agent')).toBeInTheDocument()
    expect(screen.queryByText('Screenshot')).not.toBeInTheDocument()
    expect(screen.queryByText('Open Browser')).not.toBeInTheDocument()
  })

  it('shows skill drafts awaiting review', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/api/skills/drafts')) {
        return {
          ok: true,
          json: async () => ({
            drafts: [{
              id: 'daily-report-1',
              draft_id: 'daily-report-1',
              skill_id: 'user:daily-report',
              name: 'daily-report',
              description: 'Use when writing daily reports.',
              status: 'draft',
              source: 'user',
              scopes: ['personal'],
              enabledByAgent: { personal: true, coding: false },
              path: 'AGENTS/skills/.drafts/daily-report-1',
              validation: { passed: true, issues: [], warnings: [], risks: [] },
            }],
          }),
        }
      }
      return {
        ok: true,
        json: async () => ({
          skills: [{
            id: 'using-superpowers',
            name: 'using-superpowers',
            description: 'Load relevant skills only when needed.',
            source: 'superpowers',
            enabledByAgent: { personal: true, coding: true },
            recommendedFor: ['personal', 'coding'],
            category: 'core',
            trustLevel: 'local',
          }],
          preferences: { personal: { 'using-superpowers': true }, coding: { 'using-superpowers': true } },
          defaults: { personal: {}, coding: {} },
          presets: [],
        }),
      }
    }))

    render(<Sidebar {...defaultProps} />)

    expect(await screen.findByText('Drafts awaiting review')).toBeInTheDocument()
    expect(screen.getByText('daily-report')).toBeInTheDocument()
    expect(screen.getByText('Validated')).toBeInTheDocument()
    expect(screen.getByText('Publish')).toBeInTheDocument()
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

  it('calls onClear when clicking clear button', () => {
    const onClear = vi.fn()
    render(<Sidebar {...defaultProps} onClear={onClear} />)

    fireEvent.click(screen.getByText('Clear Session'))

    expect(onClear).toHaveBeenCalled()
  })

  it('saves skill preference when toggling a skill', async () => {
    const fetchMock = vi.mocked(fetch)
    render(<Sidebar {...defaultProps} />)

    fireEvent.click(await screen.findByLabelText('Expand Core'))
    const toggle = await screen.findByLabelText('Disable using-superpowers for Personal Agent')
    fireEvent.click(toggle)

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        'http://127.0.0.1:8765/api/skills/preferences',
        expect.objectContaining({ method: 'PUT' })
      )
    })
  })

  it('saves all skills in a category when toggling the category checkbox', async () => {
    const fetchMock = vi.mocked(fetch)
    render(<Sidebar {...defaultProps} />)

    const toggle = await screen.findByLabelText('Disable all Core for Personal Agent')
    fireEvent.click(toggle)

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(([url]) => (
        url === 'http://127.0.0.1:8765/api/skills/preferences'
      ))
      expect(saveCall).toBeTruthy()
      const body = JSON.parse((saveCall?.[1] as RequestInit).body as string)
      expect(body.personal['using-superpowers']).toBe(false)
    })
  })

  it('applies a skill preset for the current agent', async () => {
    const fetchMock = vi.mocked(fetch)
    render(<Sidebar {...defaultProps} />)

    fireEvent.click(await screen.findByLabelText('Apply Personal Daily preset'))

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(([url]) => (
        url === 'http://127.0.0.1:8765/api/skills/preferences'
      ))
      expect(saveCall).toBeTruthy()
      const body = JSON.parse((saveCall?.[1] as RequestInit).body as string)
      expect(body.personal['using-superpowers']).toBe(true)
      expect(body.personal['personal:data_analysis']).toBe(true)
    })
  })

  it('expands and collapses a skill category', async () => {
    render(<Sidebar {...defaultProps} />)

    expect(await screen.findByLabelText('Expand Core')).toBeInTheDocument()
    expect(screen.queryByText('using-superpowers')).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Expand Core'))
    expect(screen.getByText('using-superpowers')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Collapse Core'))
    expect(screen.queryByText('using-superpowers')).not.toBeInTheDocument()
  })

  it('persists expanded skill categories per agent', async () => {
    render(<Sidebar {...defaultProps} />)

    fireEvent.click(await screen.findByLabelText('Expand Core'))

    expect(JSON.parse(localStorage.getItem('desktop-agent-skills-expanded:personal') || '{}')).toMatchObject({
      core: true,
    })
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
    expect(screen.queryByRole('button', { name: 'Skills' })).not.toBeInTheDocument()
  })
})
