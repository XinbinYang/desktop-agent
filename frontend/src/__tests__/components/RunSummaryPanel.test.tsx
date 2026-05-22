import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { RunSummaryPanel } from '../../components/RunSummaryPanel'
import type { RunEvent } from '../../types'

const events: RunEvent[] = [
  {
    id: '1',
    type: 'run_created',
    runId: 'run-1',
    timestamp: 1000,
    data: {
      run_id: 'run-1',
      mode: 'worktree',
      project_path: 'C:/repo',
      worktree_path: 'C:/runtime/worktrees/run-1',
      base_branch: 'main',
      base_commit: 'abc123',
    },
  },
  {
    id: '2',
    type: 'context_pack',
    runId: 'run-1',
    timestamp: 1100,
    data: {
      run_id: 'run-1',
      repo_map_summary: 'Project: C:/repo\nLanguages: python',
      files: ['app.py'],
    },
  },
  {
    id: '3',
    type: 'verification_result',
    runId: 'run-1',
    timestamp: 1200,
    data: {
      run_id: 'run-1',
      passed: true,
      command: 'python -m pytest',
      summary: 'passed',
    },
  },
  {
    id: '4',
    type: 'review_finding',
    runId: 'run-1',
    timestamp: 1300,
    data: {
      run_id: 'run-1',
      severity: 'minor',
      message: 'Add one edge-case test later',
    },
  },
  {
    id: '5',
    type: 'run_completed',
    runId: 'run-1',
    timestamp: 1400,
    data: {
      run_id: 'run-1',
      status: 'completed',
      summary: 'done',
      verification_passed: true,
      verification_command: 'python -m pytest',
      green_level: 'workspace',
      review_passed: true,
    },
  },
]

describe('RunSummaryPanel', () => {
  it('renders run context, verification, and review findings', () => {
    render(<RunSummaryPanel events={events} />)

    expect(screen.getByText('Run Summary')).toBeInTheDocument()
    expect(screen.getAllByText('run-1')[0]).toBeInTheDocument()
    expect(screen.getByText('worktree')).toBeInTheDocument()
    expect(screen.getByText(/Project: C:\/repo/)).toBeInTheDocument()
    expect(screen.getByText('Ready for you')).toBeInTheDocument()
    expect(screen.getByText('Checked with workspace.')).toBeInTheDocument()
    expect(screen.getByText(/passed: python -m pytest/)).toBeInTheDocument()
    expect(screen.getByText('Add one edge-case test later')).toBeInTheDocument()
  })

  it('invokes worktree actions', () => {
    const onApplyRun = vi.fn()
    const onMergeRun = vi.fn()
    const onDiscardRun = vi.fn()
    const onOpenWorktree = vi.fn()

    render(
      <RunSummaryPanel
        events={events}
        onOpenWorktree={onOpenWorktree}
        onApplyRun={onApplyRun}
        onMergeRun={onMergeRun}
        onDiscardRun={onDiscardRun}
      />,
    )

    fireEvent.click(screen.getByText('Open'))
    fireEvent.click(screen.getByText('Apply'))
    fireEvent.click(screen.getByText('Merge'))
    fireEvent.click(screen.getByText('Discard'))

    expect(onApplyRun).toHaveBeenCalledWith('run-1')
    expect(onMergeRun).toHaveBeenCalledWith('run-1')
    expect(onDiscardRun).toHaveBeenCalledWith('run-1')
    expect(onOpenWorktree).toHaveBeenCalledWith('run-1')
  })

  it('renders collaboration timeline and raw events', () => {
    const collabEvents: RunEvent[] = [
      {
        id: 'collab-created',
        type: 'collaboration_run_created',
        runId: 'collab_1',
        timestamp: 1000,
        data: { run_id: 'collab_1', goal: 'fix returns' },
      },
      {
        id: 'collab-answer',
        type: 'collaboration_clarification_answer',
        runId: 'collab_1',
        timestamp: 1100,
        data: {
          run_id: 'collab_1',
          answer: 'log_return',
          answered_by: 'personal_auto',
          confidence: 0.88,
        },
      },
      {
        id: 'collab-tool',
        type: 'tool_call',
        runId: 'collab_1',
        timestamp: 1200,
        data: { collaboration_run_id: 'collab_1', name: 'verify_project', result: 'ok' },
      },
    ]

    render(<RunSummaryPanel events={collabEvents} />)

    expect(screen.getByText('Collaboration Timeline')).toBeInTheDocument()
    expect(screen.getByText('Personal delegated to Coding')).toBeInTheDocument()
    expect(screen.getByText('Personal auto-answered (88%)')).toBeInTheDocument()
    expect(screen.getByText(/Coding ran verify_project/)).toBeInTheDocument()
    expect(screen.getByText('Raw events')).toBeInTheDocument()
  })
})
