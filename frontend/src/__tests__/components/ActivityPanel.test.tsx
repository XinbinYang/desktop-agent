import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ActivityPanel } from '../../components/activity/ActivityPanel'
import type { RunEvent } from '../../types'

const baseProps = {
  toolCalls: [],
  fileEdits: [],
  runEvents: [],
  onOpenFileFromChanges: vi.fn(),
  onOpenFileFromTests: vi.fn(),
  onOpenFileFromProblems: vi.fn(),
  onOpenWorktree: vi.fn(),
  onApplyRun: vi.fn(),
  onMergeRun: vi.fn(),
  onDiscardRun: vi.fn(),
}

describe('ActivityPanel', () => {
  it('shows matched and disabled skills from the latest trace', () => {
    const runEvents: RunEvent[] = [
      {
        id: 'skills-1',
        type: 'skills_matched',
        runId: 'run-1',
        timestamp: 1000,
        data: {
          skills: [
            {
              id: 'systematic-debugging',
              name: 'systematic-debugging',
              category: 'build-debug',
              source: 'superpowers',
              reason: 'Task looks like debugging or bug fixing.',
            },
          ],
          disabled_matches: [
            {
              id: 'test-driven-development',
              name: 'test-driven-development',
              category: 'quality-review',
              source: 'superpowers',
              reason: 'Disabled by user preference.',
            },
          ],
        },
      },
    ]

    render(<ActivityPanel {...baseProps} runEvents={runEvents} />)

    expect(screen.getByText('systematic-debugging')).toBeInTheDocument()
    expect(screen.getByText('Auto')).toBeInTheDocument()
    expect(screen.getByText('test-driven-development')).toBeInTheDocument()
    expect(screen.getByText('Disabled')).toBeInTheDocument()
    expect(screen.getByText('build debug')).toBeInTheDocument()
  })

  it('shows a quiet empty state before any skill trace arrives', () => {
    render(<ActivityPanel {...baseProps} />)

    expect(screen.getByText('No skill trace yet.')).toBeInTheDocument()
  })
})
