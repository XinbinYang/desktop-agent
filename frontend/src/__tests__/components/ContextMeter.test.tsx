import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ContextMeter } from '../../components/ContextMeter'
import type { ContextUsage } from '../../types'

const baseUsage: ContextUsage = {
  session_id: 's1',
  model_id: 'gpt-4o',
  model_context: 1000,
  estimated_tokens: 420,
  used_tokens: 420,
  remaining_tokens: 580,
  used_percent: 42,
  exact: false,
  source: 'estimate',
  status: 'ok',
  breakdown: { history: 300, system: 120 },
}

describe('ContextMeter', () => {
  it('shows summarized without trimmed when compaction covers older history', () => {
    render(
      <ContextMeter
        usage={{
          ...baseUsage,
          compaction_active: true,
          context_truncated: true,
          unsummarized_context_truncated: false,
          transcript_message_count: 30,
          context_message_count: 10,
        }}
      />,
    )

    expect(screen.getByText('summarized')).toBeInTheDocument()
    expect(screen.queryByText('trimmed')).not.toBeInTheDocument()
  })

  it('shows trimmed when unsummarized context is still clipped', () => {
    render(
      <ContextMeter
        usage={{
          ...baseUsage,
          compaction_active: true,
          context_truncated: true,
          unsummarized_context_truncated: true,
          transcript_message_count: 40,
          context_message_count: 12,
        }}
      />,
    )

    expect(screen.getByText('summarized')).toBeInTheDocument()
    expect(screen.getByText('trimmed')).toBeInTheDocument()
  })

  it('still compacts on click', () => {
    const onCompact = vi.fn()
    render(<ContextMeter usage={baseUsage} onCompact={onCompact} />)

    fireEvent.click(screen.getByTitle(/Context 42\.0%/))

    expect(onCompact).toHaveBeenCalled()
  })
})
