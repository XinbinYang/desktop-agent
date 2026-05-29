import { describe, expect, it } from 'vitest'
import { buildCollaborationTimeline, collaborationEventsForRun } from '../../lib/collaborationTimeline'
import type { RunEvent } from '../../types'

const event = (type: RunEvent['type'], data: Record<string, any>, timestamp = 1000): RunEvent => ({
  id: `${type}-${timestamp}`,
  type,
  runId: data.run_id || data.collaboration_run_id,
  timestamp,
  data,
})

describe('collaborationTimeline', () => {
  it('maps collaboration events into user-readable phases', () => {
    const events: RunEvent[] = [
      event('collaboration_run_created', { run_id: 'collab_1', goal: 'fix returns' }, 1000),
      event('collaboration_clarification_request', {
        run_id: 'collab_1',
        request_id: 'clar_1',
        question: 'Use simple_return or log_return?',
      }, 1100),
      event('decision_required', {
        run_id: 'collab_1',
        kind: 'clarification',
        request_id: 'clar_1',
        reason: 'Use simple_return or log_return?',
      }, 1110),
      event('collaboration_clarification_answer', {
        run_id: 'collab_1',
        request_id: 'clar_1',
        answer: 'log_return',
        answered_by: 'personal_auto',
        confidence: 0.91,
      }, 1200),
      event('tool_call', {
        collaboration_run_id: 'collab_1',
        name: 'verify_project',
        result: 'exit_code: 0\nok',
      }, 1300),
      event('verification_result', {
        collaboration_run_id: 'collab_1',
        passed: true,
        command: 'npm test',
      }, 1400),
      event('collaboration_run_completed', {
        run_id: 'collab_1',
        status: 'completed',
        summary: 'done',
      }, 1500),
    ]

    const timeline = buildCollaborationTimeline(events)

    expect(timeline.map((item) => item.title)).toEqual([
      'Personal delegated to Coding',
      'Coding asked Personal',
      'Personal auto-answered (91%)',
      'Coding ran verify_project',
      'Verification passed',
      'Collaboration completed',
    ])
    expect(timeline.find((item) => item.kind === 'answer')?.actor).toBe('personal')
  })

  it('distinguishes child coding completion from parent collaboration completion', () => {
    const timeline = buildCollaborationTimeline([
      event('run_completed', {
        run_id: 'coding_child',
        collaboration_run_id: 'collab_1',
        status: 'completed',
        summary: 'Run completed after 2 iteration(s).',
      }, 1000),
      event('collaboration_run_completed', {
        run_id: 'collab_1',
        status: 'failed',
        summary: 'Verification evidence is required.',
      }, 1100),
    ])

    expect(timeline.map((item) => item.title)).toEqual([
      'Coding run completed',
      'Collaboration failed',
    ])
  })

  it('maps collaboration model errors as failed timeline items', () => {
    const timeline = buildCollaborationTimeline([
      event('error', {
        run_id: 'coding_child',
        collaboration_run_id: 'collab_1',
        message: 'Model call failed: [Errno 11001] getaddrinfo failed',
      }, 1000),
    ])

    expect(timeline[0]).toMatchObject({
      actor: 'system',
      title: 'Model call failed',
      status: 'failed',
    })
  })

  it('filters events by collaboration_run_id before run_id', () => {
    const events: RunEvent[] = [
      event('tool_call', { run_id: 'outer_run', collaboration_run_id: 'collab_1', name: 'pytest' }),
      event('tool_call', { run_id: 'outer_run', collaboration_run_id: 'collab_2', name: 'vitest' }),
    ]

    expect(collaborationEventsForRun(events, 'collab_1')).toHaveLength(1)
    expect(collaborationEventsForRun(events, 'collab_1')[0].data.name).toBe('pytest')
  })
})
