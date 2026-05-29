import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CollaborationTrack } from '../../components/CollaborationTrack'
import type { RunEvent } from '../../types'

describe('CollaborationTrack', () => {
  it('shows live phases and Personal auto-answer details', () => {
    const events: RunEvent[] = [
      {
        id: 'run',
        type: 'collaboration_run_created',
        runId: 'collab_1',
        timestamp: 1000,
        data: { run_id: 'collab_1', goal: 'fix returns' },
      },
      {
        id: 'answer',
        type: 'collaboration_clarification_answer',
        runId: 'collab_1',
        timestamp: 1100,
        data: {
          run_id: 'collab_1',
          answer: 'log_return',
          answered_by: 'personal_auto',
          reason: 'Safe technical default.',
          confidence: 0.93,
        },
      },
    ]

    render(<CollaborationTrack events={events} status="running" teamProgress={[]} />)

    expect(screen.getByText('Personal ↔ Coding')).toBeInTheDocument()
    expect(screen.getAllByText('Personal auto-answered (93%)').length).toBeGreaterThan(0)
    expect(screen.getByText('personal_auto')).toBeInTheDocument()
    expect(screen.getByText(/Reason: Safe technical default/)).toBeInTheDocument()
  })

  it('keeps manual clarification controls working', () => {
    const onAnswer = vi.fn()
    render(
      <CollaborationTrack
        status="waiting_clarification"
        pendingClarification={{
          request_id: 'clar_1',
          question: 'Use simple_return or log_return?',
          options: ['log_return', 'simple_return'],
          recommendation: 'log_return',
        }}
        onAnswerClarification={onAnswer}
      />,
    )

    fireEvent.click(screen.getByText('log_return'))
    fireEvent.click(screen.getByText('Send'))

    expect(onAnswer).toHaveBeenCalledWith('log_return')
  })
})
