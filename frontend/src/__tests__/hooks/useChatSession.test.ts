import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useChatSession } from '../../hooks/useChatSession'
import type { WS_EVENT } from '../../types'
import { loadSession, deleteSessionData } from '../../lib/db'

// Mock useWebSocket
vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({
    isConnected: true,
    send: vi.fn(),
    disconnect: vi.fn(),
  })),
}))

// Mock idb
vi.mock('../../lib/db', () => ({
  saveSession: vi.fn(),
  loadSession: vi.fn(() => Promise.resolve(undefined)),
  deleteSessionData: vi.fn(),
  saveDraft: vi.fn(),
  loadDraft: vi.fn(() => Promise.resolve(undefined)),
  deleteDraft: vi.fn(),
}))

import { useWebSocket } from '../../hooks/useWebSocket'

const mockedUseWebSocket = vi.mocked(useWebSocket)
const mockedLoadSession = vi.mocked(loadSession)
const mockedDeleteSessionData = vi.mocked(deleteSessionData)

describe('useChatSession', () => {
  const mockSend = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.setItem('desktop-agent-chat-mode', 'agent')
    localStorage.setItem('desktop-agent-thinking-intensity', 'medium')
    mockSend.mockReset()
    mockSend.mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve({ json: () => Promise.resolve({ error: 'not found' }) })
    ))
    mockedUseWebSocket.mockReturnValue({
      isConnected: true,
      send: mockSend,
      disconnect: vi.fn(),
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('initializes with empty state', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))
    expect(result.current.messages).toEqual([])
    expect(result.current.toolCalls).toEqual([])
    expect(result.current.isRunning).toBe(false)
  })

  it('sends message and adds user message', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.sendMessage('hello')
    })

    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].role).toBe('user')
    expect(result.current.messages[0].content).toBe('hello')
    expect(result.current.isRunning).toBe(true)
    expect(mockSend).toHaveBeenCalledWith({
      type: 'chat',
      text: 'hello',
      model_id: 'gpt-4o',
      agent_type: 'personal',
      role_id: 'desktop-agent',
      image_base64: undefined,
      chat_mode: 'agent',
      thinking_intensity: 'medium',
    })
  })

  it('stops running when websocket send fails', () => {
    mockSend.mockImplementation((payload: { type?: string }) =>
      payload?.type === 'chat' ? false : true,
    )
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.sendMessage('hello')
    })

    expect(result.current.isRunning).toBe(false)
    expect(result.current.terminalLogs.some((line) => line.includes('WebSocket'))).toBe(true)
  })

  it('queues guidance instead of chat when sending while running', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({ type: 'status', data: { status: 'thinking' } })
      result.current.sendMessage('prefer the smaller fix')
    })

    expect(mockSend).toHaveBeenLastCalledWith({
      type: 'queue_task_guidance',
      text: 'prefer the smaller fix',
      image_base64: undefined,
    })
    expect(result.current.messages).toHaveLength(0)
  })

  it('tracks task guidance websocket events', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'task_guidance_queued',
        data: {
          item: { id: 'tg_1', text: 'note', status: 'queued', created_at: 1 },
        },
      })
    })
    expect(result.current.taskGuidanceItems).toHaveLength(1)

    act(() => {
      messageHandler?.({
        type: 'task_guidance_applied',
        data: {
          items: [{ id: 'tg_1', text: 'note', status: 'applied', created_at: 1, applied_at: 2 }],
        },
      })
    })
    expect(result.current.taskGuidanceItems[0].status).toBe('applied')

    act(() => {
      messageHandler?.({
        type: 'task_guidance_consumed',
        data: {
          items: [{ id: 'tg_1', text: 'note', status: 'consumed', created_at: 1, consumed_at: 3 }],
        },
      })
    })
    expect(result.current.taskGuidanceItems).toHaveLength(0)
  })

  it('keeps running after completed status until run_completed or done', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({ type: 'status', data: { status: 'thinking' } })
    })
    expect(result.current.isRunning).toBe(true)

    act(() => {
      messageHandler?.({ type: 'status', data: { status: 'completed' } })
    })
    expect(result.current.isRunning).toBe(true)

    act(() => {
      messageHandler?.({ type: 'run_completed', data: { status: 'completed', summary: 'ok' } })
    })
    expect(result.current.isRunning).toBe(false)
  })

  it('falls back to done when no run_completed event arrives', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({ type: 'status', data: { status: 'thinking' } })
      messageHandler?.({ type: 'status', data: { status: 'completed' } })
    })
    expect(result.current.isRunning).toBe(true)

    act(() => {
      messageHandler?.({ type: 'done', data: {} })
    })
    expect(result.current.isRunning).toBe(false)
  })

  it('auto-sends unread stale guidance after done', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))
    mockSend.mockClear()

    act(() => {
      messageHandler?.({ type: 'status', data: { status: 'thinking' } })
      messageHandler?.({
        type: 'task_guidance_stale',
        data: {
          items: [{ id: 'tg_1', text: 'continue as a new question', status: 'stale', created_at: 1 }],
          all_items: [],
        },
      })
    })
    expect(result.current.taskGuidanceItems).toHaveLength(0)

    act(() => {
      messageHandler?.({ type: 'done', data: {} })
    })

    expect(mockSend).toHaveBeenCalledWith({
      type: 'chat',
      text: 'continue as a new question',
      model_id: 'gpt-4o',
      agent_type: 'personal',
      role_id: 'desktop-agent',
      image_base64: undefined,
      chat_mode: 'agent',
      thinking_intensity: 'medium',
    })
    expect(result.current.messages.some((message) => message.role === 'user' && message.content === 'continue as a new question')).toBe(true)
  })

  it('removes an optimistic chat bubble when the backend queues it as guidance', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.sendMessage('queued note')
    })
    expect(result.current.messages.map((m) => m.content)).toEqual(['queued note'])

    act(() => {
      messageHandler?.({
        type: 'task_guidance_queued',
        data: {
          item: { id: 'tg_1', text: 'queued note', status: 'queued', created_at: 1 },
        },
      })
    })

    expect(result.current.messages).toHaveLength(0)
    expect(result.current.taskGuidanceItems).toHaveLength(1)
  })

  it('marks the session running when reconnect receives live run status', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({ type: 'status', data: { status: 'thinking' } })
    })

    expect(result.current.isRunning).toBe(true)
  })

  it('handles content event by appending to assistant message', async () => {
    vi.useFakeTimers()
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    // First content event creates assistant message with a text block
    act(() => {
      messageHandler?.({ type: 'content', data: { text: 'Hello' } })
    })

    expect(result.current.messages).toHaveLength(0)

    act(() => {
      vi.advanceTimersByTime(60)
    })

    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].blocks).toBeDefined()
    expect(result.current.messages[0].blocks![0].type).toBe('text')
    expect((result.current.messages[0].blocks![0] as { text: string }).text).toBe('Hello')

    // Second content event merges into the same text block
    act(() => {
      messageHandler?.({ type: 'content', data: { text: ' world' } })
    })

    act(() => {
      vi.advanceTimersByTime(60)
    })

    // Re-read blocks from the updated state (not stale reference)
    expect(result.current.messages[0].blocks![0].type).toBe('text')
    expect((result.current.messages[0].blocks![0] as { text: string }).text).toBe('Hello world')
    vi.useRealTimers()
  })

  it('creates a replaceable assistant placeholder while waiting for the first streamed token', () => {
    vi.useFakeTimers()
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.sendMessage('hello')
      messageHandler?.({ type: 'status', data: { status: 'thinking' } })
    })

    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[1].blocks?.[0]).toMatchObject({
      type: 'thinking',
      text: 'Waiting for model response...',
    })

    act(() => {
      messageHandler?.({ type: 'content', data: { text: 'Hello' } })
      vi.advanceTimersByTime(60)
    })

    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[1].blocks).toEqual([
      expect.objectContaining({ type: 'text', text: 'Hello' }),
    ])
    vi.useRealTimers()
  })

  it('replaces the waiting placeholder with streamed reasoning', () => {
    vi.useFakeTimers()
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.sendMessage('hello')
      messageHandler?.({ type: 'status', data: { status: 'thinking' } })
      messageHandler?.({ type: 'reasoning', data: { text: 'checking context' } })
      vi.advanceTimersByTime(60)
    })

    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[1].blocks).toEqual([
      expect.objectContaining({ type: 'thinking', text: 'checking context' }),
    ])
    vi.useRealTimers()
  })

  it('records skills_matched events for activity trace', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'skills_matched',
        data: {
          run_id: 'run-1',
          skills: [{ id: 'systematic-debugging', name: 'systematic-debugging' }],
          disabled_matches: [{ id: 'test-driven-development', name: 'test-driven-development' }],
        },
      })
    })

    expect(result.current.runEvents).toHaveLength(1)
    expect(result.current.runEvents[0].type).toBe('skills_matched')
    expect(result.current.runEvents[0].data.skills).toHaveLength(1)
    expect(result.current.terminalLogs.some((line) => line.includes('[Skills] 1 matched, 1 disabled'))).toBe(true)
  })

  it('submits plan decisions in one websocket message without appending Answers block', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'plan_questions',
        data: {
          phase: 'awaiting_decision',
          pending_clarification: true,
          questions: [{
            id: 'scope',
            prompt: 'What scope?',
            allow_multiple: false,
            options: [{ id: 'small', label: 'Small' }, { id: 'large', label: 'Large' }],
          }],
        },
      })
    })

    expect(result.current.chatMode).toBe('plan')
    expect(result.current.planState.questions).toHaveLength(1)
    expect(result.current.messages.some((msg) => msg.blocks?.some((block) => block.type === 'plan_questions'))).toBe(false)

    act(() => {
      result.current.submitPlanDecisions([{
        question_id: 'scope',
        selected: ['small'],
        other_text: 'Keep manual fallback',
        skipped: false,
      }])
    })

    expect(mockSend).toHaveBeenCalledWith({
      type: 'submit_plan_decisions',
      answers: [{
        question_id: 'scope',
        selected: ['small'],
        other_text: 'Keep manual fallback',
        skipped: false,
      }],
    })
    expect(result.current.planState.phase).toBe('planning')
    expect(result.current.isRunning).toBe(true)
    expect(result.current.messages.some((msg) => msg.blocks?.some((block) => block.type === 'plan_answers'))).toBe(false)
  })

  it('plan_status clears stale plan goal when backend resets plan mode', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'plan_status',
        data: {
          mode: 'plan',
          phase: 'awaiting_approval',
          goal: 'old goal',
          draft: '# old plan',
          structured_plan: {
            goal: 'old goal',
            assumptions: [],
            steps: [],
            todos: [],
            risks: [],
            acceptance_criteria: [],
          },
          questions: [],
          todos: [],
          decisions: {},
          approved: false,
          pending_clarification: false,
        },
      })
    })

    expect(result.current.planState.goal).toBe('old goal')
    expect(result.current.planState.structured_plan?.goal).toBe('old goal')

    act(() => {
      messageHandler?.({
        type: 'plan_status',
        data: {
          mode: 'plan',
          phase: 'idle',
          goal: '',
          draft: '',
          structured_plan: null,
          questions: [],
          todos: [],
          decisions: {},
          approved: false,
          pending_clarification: false,
        },
      })
    })

    expect(result.current.planState.phase).toBe('idle')
    expect(result.current.planState.goal).toBe('')
    expect(result.current.planState.structured_plan).toBeNull()
  })

  it('hydrates a full backend history snapshot', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'history_snapshot',
        data: {
          session_id: 'session-1',
          model_id: 'gpt-4o',
          role_id: 'desktop-agent',
          chat_mode: 'agent',
          messages: [
            { role: 'system', content: 'system' },
            { role: 'user', content: 'hello history' },
            {
              role: 'assistant',
              content: 'I will read it',
              tool_calls: [{
                id: 'call-1',
                type: 'function',
                function: { name: 'file_read', arguments: '{"path":"a.txt"}' },
              }],
            },
            { role: 'tool', tool_call_id: 'call-1', name: 'file_read', content: 'file body' },
          ],
        },
      })
    })

    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0].role).toBe('user')
    expect(result.current.messages[0].content).toBe('hello history')
    expect(result.current.messages[1].blocks?.some((b) => b.type === 'tool_call')).toBe(true)
    expect(result.current.toolCalls[0].result).toBe('file body')
  })

  it('hydrates command notices from backend snapshots', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'history_snapshot',
        data: {
          session_id: 'session-1',
          model_id: 'gpt-4o',
          role_id: 'desktop-agent',
          chat_mode: 'agent',
          messages: [
            { role: 'system', content: 'system prompt' },
            {
              role: 'system',
              source: 'command_notice',
              level: 'success',
              content: 'New session started - model: gpt-4o',
            },
          ],
        },
      })
    })

    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0]).toMatchObject({
      role: 'system',
      source: 'command_notice',
      noticeLevel: 'success',
      content: 'New session started - model: gpt-4o',
    })
  })

  it('does not render internal-source messages as user bubbles', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'history_snapshot',
        data: {
          session_id: 'session-1',
          model_id: 'gpt-4o',
          role_id: 'desktop-agent',
          chat_mode: 'agent',
          messages: [
            { role: 'system', content: 'system' },
            { role: 'user', content: 'real question', source: 'user' },
            { role: 'user', content: '[BUILD ALREADY CLICKED] ...', source: 'internal' },
            { role: 'assistant', content: 'answer' },
            { role: 'user', content: '[VERIFICATION REQUIRED] ...', source: 'internal' },
          ],
        },
      })
    })

    const userMsgs = result.current.messages.filter((m) => m.role === 'user')
    expect(userMsgs).toHaveLength(1)
    expect(userMsgs[0].content).toBe('real question')
    expect(
      result.current.messages.some((m) => m.content.includes('BUILD ALREADY CLICKED')),
    ).toBe(false)
    expect(
      result.current.messages.some((m) => m.content.includes('VERIFICATION REQUIRED')),
    ).toBe(false)
  })

  it('hydrates multimodal and image-only user snapshot messages without empty bubbles', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'history_snapshot',
        data: {
          session_id: 'session-1',
          model_id: 'gpt-4o',
          role_id: 'desktop-agent',
          chat_mode: 'agent',
          messages: [
            {
              role: 'user',
              content: [
                { type: 'input_text', text: 'describe this' },
                { type: 'image_url', image_url: { url: 'data:image/png;base64,abc123' } },
              ],
            },
            {
              role: 'user',
              content: [
                { type: 'image_url', image_url: { url: 'data:image/png;base64,imgonly' } },
              ],
            },
          ],
        },
      })
    })

    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[0].content).toBe('describe this')
    expect(result.current.messages[0].imageBase64).toBe('abc123')
    expect(result.current.messages[1].content).toBe('[image]')
    expect(result.current.messages[1].imageBase64).toBe('imgonly')
  })

  it('merges history snapshots without dropping optimistic user messages', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.sendMessage('still pending')
      messageHandler?.({
        type: 'history_snapshot',
        data: {
          session_id: 'session-1',
          model_id: 'gpt-4o',
          role_id: 'desktop-agent',
          chat_mode: 'agent',
          messages: [
            { role: 'user', content: 'old server message', message_id: 'server-1' },
          ],
        },
      })
    })

    expect(result.current.messages.map((m) => m.content)).toEqual([
      'old server message',
      'still pending',
    ])
  })

  it('uses IndexedDB as warm cache but lets backend snapshot repair empty cached users', async () => {
    mockedLoadSession.mockResolvedValueOnce({
      sessionId: 'session-cache',
      messages: [{ id: 'bad-user', role: 'user', content: '', isTool: false }],
      toolCalls: [],
      timestamp: Date.now(),
    } as any)
    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({
          session_id: 'session-cache',
          model_id: 'gpt-4o',
          role_id: 'desktop-agent',
          chat_mode: 'agent',
          messages: [{ role: 'user', content: 'server repaired', message_id: 'm1' }],
        }),
      })
    ))

    const { result } = renderHook(() => useChatSession('session-cache', 'gpt-4o'))

    await waitFor(() => {
      expect(result.current.messages.map((m) => m.content)).toEqual(['server repaired'])
    })
  })

  it('does not preserve stale cached user messages as pending optimistic sends', async () => {
    mockedLoadSession.mockResolvedValueOnce({
      sessionId: 'session-cache',
      messages: [{ id: 'stale-user', role: 'user', content: 'stale cached user', isTool: false }],
      toolCalls: [],
      timestamp: Date.now(),
    } as any)
    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({
          session_id: 'session-cache',
          model_id: 'gpt-4o',
          role_id: 'desktop-agent',
          chat_mode: 'agent',
          messages: [{ role: 'user', content: 'server only', message_id: 'm1' }],
        }),
      })
    ))

    const { result } = renderHook(() => useChatSession('session-cache', 'gpt-4o'))

    await waitFor(() => {
      expect(result.current.messages.map((m) => m.content)).toEqual(['server only'])
    })
  })

  it('clears stale IndexedDB cache when the backend has no matching session', async () => {
    mockedLoadSession.mockResolvedValueOnce({
      sessionId: 'missing-session',
      messages: [{ id: 'stale-user', role: 'user', content: 'stale cached user', isTool: false }],
      toolCalls: [],
      timestamp: Date.now(),
    } as any)
    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve({
        json: () => Promise.resolve({
          error: { category: 'not_found', message: 'Session not found', retryable: false },
        }),
      })
    ))

    const { result } = renderHook(() => useChatSession('missing-session', 'gpt-4o'))

    await waitFor(() => {
      expect(mockedDeleteSessionData).toHaveBeenCalledWith('missing-session')
    })
    expect(result.current.messages).toEqual([])
  })

  it('handles tool_call event', async () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'tool_call',
        data: {
          name: 'file_read',
          args: { path: 'test.txt' },
          result: 'file content',
          run_id: 'run-1',
          tool_call_id: 'call-1',
          duration_ms: 12,
        },
      })
    })

    expect(result.current.toolCalls).toHaveLength(1)
    expect(result.current.toolCalls[0].name).toBe('file_read')
    expect(result.current.toolCalls[0].runId).toBe('run-1')
    expect(result.current.toolCalls[0].toolCallId).toBe('call-1')
    expect(result.current.toolCalls[0].durationMs).toBe(12)
    // tool_call also adds an inline block to messages
    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].blocks).toBeDefined()
    expect(result.current.messages[0].blocks![0].type).toBe('tool_call')
  })

  it('hides internal plan tool events from visible tool state', async () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'status',
        data: { status: 'executing', tool: 'plan_write_draft', tool_call_id: 'plan-status' },
      })
      for (const name of ['plan_ask_questions', 'plan_write_draft', 'plan_update_todos']) {
        messageHandler?.({
          type: 'tool_call',
          data: {
            name,
            args: {},
            result: 'ok',
            run_id: 'run-1',
            tool_call_id: `call-${name}`,
          },
        })
      }
      messageHandler?.({
        type: 'tool_result',
        data: {
          name: 'plan_update_todos',
          args: {},
          output: 'ok',
          error: '',
          tool_call_id: 'direct-plan-update',
        },
      })
    })

    expect(result.current.toolCalls).toEqual([])
    expect(result.current.messages.flatMap((msg) => msg.blocks || [])).not.toContainEqual(
      expect.objectContaining({ type: 'tool_call' }),
    )
  })

  it('filters internal plan tool calls from history snapshots', async () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'history_snapshot',
        data: {
          messages: [
            {
              role: 'assistant',
              content: '',
              message_id: 'assistant-plan',
              tool_calls: [{
                id: 'plan-call',
                function: { name: 'plan_write_draft', arguments: '{}' },
              }],
            },
            {
              role: 'tool',
              name: 'plan_write_draft',
              tool_call_id: 'plan-call',
              content: 'Plan draft submitted for review.',
            },
          ],
        },
      })
    })

    expect(result.current.toolCalls).toEqual([])
    expect(result.current.messages).toEqual([])
  })

  it('seals an open thinking block when a tool lands and starts a new one after', async () => {
    vi.useFakeTimers()
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return { isConnected: true, send: mockSend, disconnect: vi.fn() }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({ type: 'reasoning', data: { text: 'first thought ' } })
      messageHandler?.({ type: 'reasoning', data: { text: 'continued' } })
    })

    act(() => {
      vi.advanceTimersByTime(60)
    })

    let blocks = result.current.messages[0].blocks!
    const thinking0 = blocks.find((b) => b.type === 'thinking') as any
    expect(thinking0.text).toBe('first thought continued')
    expect(thinking0.complete).toBeFalsy()
    expect(typeof thinking0.startedAt).toBe('number')

    act(() => {
      messageHandler?.({
        type: 'tool_call',
        data: { name: 'shell_execute', args: { command: 'ls' }, result: 'ok', tool_call_id: 'c1', duration_ms: 5 },
      })
    })

    blocks = result.current.messages[0].blocks!
    const sealed = blocks.find((b) => b.type === 'thinking') as any
    expect(sealed.complete).toBe(true)
    expect(typeof sealed.endedAt).toBe('number')

    act(() => {
      messageHandler?.({ type: 'reasoning', data: { text: 'second thought' } })
    })

    act(() => {
      vi.advanceTimersByTime(60)
    })

    blocks = result.current.messages[0].blocks!
    const thinkingBlocks = blocks.filter((b) => b.type === 'thinking') as any[]
    expect(thinkingBlocks).toHaveLength(2)
    expect(thinkingBlocks[1].text).toBe('second thought')
    expect(thinkingBlocks[1].complete).toBeFalsy()
  })

  it('handles tool_result event', async () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'tool_result',
        data: {
          name: 'get_screen_size',
          args: {},
          output: '1920x1080',
          error: '',
        },
      })
    })

    expect(result.current.toolCalls).toHaveLength(1)
    expect(result.current.toolCalls[0].name).toBe('get_screen_size')
    expect(result.current.toolCalls[0].result).toBe('1920x1080')
  })

  it('handles tool_result image event', async () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'tool_result',
        data: {
          name: 'screenshot',
          args: {},
          output: '',
          error: '',
          image: 'abc123',
        },
      })
    })

    expect(result.current.toolCalls).toHaveLength(1)
    // tool_result + image = 2 blocks on same assistant message
    expect(result.current.messages).toHaveLength(1)
    const blocks = result.current.messages[0].blocks
    expect(blocks).toBeDefined()
    const imageBlock = blocks!.find((b) => b.type === 'image')
    expect(imageBlock).toBeDefined()
    expect((imageBlock as { type: 'image'; base64: string }).base64).toBe('abc123')
  })

  it('handles error event and stops running', async () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.sendMessage('test')
    })
    expect(result.current.isRunning).toBe(true)

    act(() => {
      messageHandler?.({
        type: 'error',
        data: { message: 'Something went wrong' },
      })
    })

    expect(result.current.isRunning).toBe(false)
    expect(result.current.messages.some((m) => m.role === 'system')).toBe(true)
  })

  it('removes the waiting placeholder when the model call fails before tokens arrive', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.sendMessage('hello')
      messageHandler?.({ type: 'status', data: { status: 'thinking' } })
      messageHandler?.({
        type: 'error',
        data: { message: 'Model call failed: DeepSeek stream failed: 400' },
      })
    })

    expect(result.current.messages.map((m) => m.role)).toEqual(['user', 'system'])
    expect(
      result.current.messages.some((m) => m.blocks?.some((block) =>
        block.type === 'thinking' && block.text === 'Waiting for model response...'
      )),
    ).toBe(false)
  })

  it('handles worker events by attaching to dispatch tool call', async () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() =>
      useChatSession('test', 'gpt-4o', 'code-expert')
    )

    // First, trigger a dispatch_worker tool_call
    act(() => {
      messageHandler?.({
        type: 'tool_call',
        data: {
          name: 'dispatch_worker',
          args: { task: 'Test', profile: 'code' },
          result: 'Working...',
        },
      })
    })

    // Verify tool call was recorded
    expect(result.current.toolCalls.length).toBeGreaterThanOrEqual(1)

    // Then trigger worker_start
    act(() => {
      messageHandler?.({
        type: 'worker_start',
        data: { worker_id: 'w1' },
      })
    })

    expect(result.current.toolCalls[0].workerEvents).toHaveLength(1)
    expect(result.current.toolCalls[0].workerEvents![0].type).toBe('worker_start')

    // Trigger worker_done
    act(() => {
      messageHandler?.({
        type: 'worker_done',
        data: {
          worker_id: 'w1',
          status: 'completed',
          result: 'All done',
          iterations: 3,
          duration_ms: 5000,
        },
      })
    })

    expect(result.current.toolCalls[0].workerEvents).toHaveLength(2)
    expect(result.current.toolCalls[0].workerEvents![1].status).toBe('completed')
  })

  it('keeps worker events that arrive before dispatch tool completion', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('test', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'status',
        data: { status: 'executing', tool: 'dispatch_worker', tool_call_id: 'parent_1' },
      })
      messageHandler?.({
        type: 'worker_start',
        data: {
          worker_id: 'w1',
          parent_tool_call_id: 'parent_1',
          task: 'Inspect',
          status: 'running',
        },
      })
      messageHandler?.({
        type: 'tool_call',
        data: {
          name: 'dispatch_worker',
          args: { task: 'Inspect' },
          result: 'done',
          tool_call_id: 'parent_1',
        },
      })
    })

    expect(result.current.toolCalls[0].workerEvents).toHaveLength(1)
    expect(result.current.toolCalls[0].workerEvents![0].task).toBe('Inspect')
  })

  it('records file_edit events', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('test', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'file_edit',
        data: {
          path: 'src/a.ts',
          operation: 'modify',
          unified_diff: 'diff',
          stats: { added: 1, removed: 1 },
          truncated: false,
        },
      })
    })

    expect(result.current.fileEdits).toHaveLength(1)
    expect(result.current.messages[0].blocks?.[0].type).toBe('file_edit')
  })

  it('resets session state', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.sendMessage('test')
    })

    act(() => {
      result.current.resetSession()
    })

    expect(result.current.messages).toEqual([])
    expect(result.current.toolCalls).toEqual([])
    expect(result.current.isRunning).toBe(false)
  })

  it('setChatMode sends set_chat_mode to the server', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.setChatMode('plan')
    })

    expect(result.current.chatMode).toBe('plan')
    expect(mockSend).toHaveBeenCalledWith({ type: 'set_chat_mode', chat_mode: 'plan' })
  })

  it('sends the next message in plan mode immediately after clicking Plan', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.setChatMode('plan')
      result.current.sendMessage('plan this')
    })

    expect(mockSend).toHaveBeenLastCalledWith({
      type: 'chat',
      text: 'plan this',
      model_id: 'gpt-4o',
      agent_type: 'personal',
      role_id: 'desktop-agent',
      image_base64: undefined,
      chat_mode: 'plan',
      thinking_intensity: 'medium',
    })
  })

  it('setThinkingIntensity sends set_thinking_intensity to the server', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.setThinkingIntensity('high')
    })

    expect(result.current.thinkingIntensity).toBe('high')
    expect(mockSend).toHaveBeenCalledWith({ type: 'set_thinking_intensity', thinking_intensity: 'high' })
  })

  it('sends build pause/end controls', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.pauseBuild()
      result.current.endBuild()
    })

    expect(mockSend).toHaveBeenCalledWith({ type: 'pause_build' })
    expect(mockSend).toHaveBeenCalledWith({ type: 'end_build' })
    expect(result.current.isRunning).toBe(false)
  })

  it('sends plan snapshot with build and ignores build when no draft is ready', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.buildPlan()
    })
    expect(mockSend).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'build_plan' }))

    act(() => {
      messageHandler?.({
        type: 'plan_draft',
        data: {
          phase: 'awaiting_approval',
          goal: 'Build the plan',
          draft: '# Plan',
          todos: [{ id: 't1', title: 'First todo', status: 'pending' }],
          structured_plan: null,
        },
      })
    })

    act(() => {
      result.current.buildPlan()
    })

    act(() => {
      result.current.buildPlan()
    })

    expect(mockSend).toHaveBeenCalledWith(expect.objectContaining({
      type: 'build_plan',
      plan_state: expect.objectContaining({
        phase: 'awaiting_approval',
        draft: '# Plan',
      }),
    }))
    expect(mockSend.mock.calls.filter(([payload]) => payload?.type === 'build_plan')).toHaveLength(1)
    expect(result.current.planState.phase).toBe('approved_waiting_build')
  })

  it('sends reset, compact, and rewind session control messages', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.resetContext('new', true)
      result.current.compactSession(false)
      result.current.rewindToCheckpoint('chk_1')
    })

    expect(mockSend).toHaveBeenCalledWith({
      type: 'reset_context',
      command: 'new',
      greet: true,
      model_id: 'gpt-4o',
      agent_type: 'personal',
      role_id: 'desktop-agent',
    })
    expect(mockSend).toHaveBeenCalledWith({ type: 'compact', force: false, focus: '', source: 'ui' })
    expect(mockSend).toHaveBeenCalledWith({
      type: 'rewind',
      checkpoint_id: 'chk_1',
      retry: true,
      model_id: 'gpt-4o',
      agent_type: 'personal',
      role_id: 'desktop-agent',
      chat_mode: 'agent',
      thinking_intensity: 'medium',
    })
  })

  it('stores context_usage and compacted context payloads', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({
        type: 'context_usage',
        data: {
          session_id: 'session-1',
          model_id: 'gpt-4o',
          model_context: 1000,
          estimated_tokens: 500,
          used_tokens: 500,
          remaining_tokens: 500,
          used_percent: 50,
          exact: false,
          source: 'estimate',
          status: 'ok',
          breakdown: { history: 400, system: 100 },
        },
      })
    })

    expect(result.current.contextUsage?.used_percent).toBe(50)

    act(() => {
      messageHandler?.({
        type: 'compacted',
        data: {
          skipped: false,
          before_message_count: 20,
          after_message_count: 6,
          context_usage: {
            session_id: 'session-1',
            model_id: 'gpt-4o',
            model_context: 1000,
            estimated_tokens: 250,
            used_tokens: 250,
            remaining_tokens: 750,
            used_percent: 25,
            exact: false,
            source: 'estimate',
            status: 'ok',
            breakdown: { history: 150, system: 100 },
          },
        },
      })
    })

    expect(result.current.contextUsage?.used_percent).toBe(25)
    expect(result.current.isRunning).toBe(false)
  })

  it('applies chat_mode events from the server', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({ type: 'chat_mode', data: { chat_mode: 'plan' } })
    })
    expect(result.current.chatMode).toBe('plan')

    act(() => {
      messageHandler?.({ type: 'chat_mode', data: { chat_mode: 'agent' } })
    })
    expect(result.current.chatMode).toBe('agent')
  })

  it('applies thinking_intensity events from the server', () => {
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      messageHandler?.({ type: 'thinking_intensity', data: { thinking_intensity: 'low' } })
    })

    expect(result.current.thinkingIntensity).toBe('low')
  })

  it('history_snapshot does not downgrade plan to agent when plan phase is idle', () => {
    localStorage.setItem('desktop-agent-chat-mode', 'plan')
    let messageHandler: ((msg: WS_EVENT) => void) | undefined
    mockedUseWebSocket.mockImplementation((_sessionId, onMessage) => {
      messageHandler = onMessage
      return {
        isConnected: true,
        send: mockSend,
        disconnect: vi.fn(),
      }
    })

    const { result } = renderHook(() => useChatSession('session-merge', 'gpt-4o'))

    expect(result.current.chatMode).toBe('plan')

    act(() => {
      messageHandler?.({
        type: 'history_snapshot',
        data: {
          session_id: 'session-merge',
          model_id: 'gpt-4o',
          role_id: 'desktop-agent',
          chat_mode: 'agent',
          plan_state: {
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
          },
          messages: [],
        },
      })
    })

    expect(result.current.chatMode).toBe('plan')
    expect(mockSend).toHaveBeenCalledWith({ type: 'set_chat_mode', chat_mode: 'plan' })
    localStorage.setItem('desktop-agent-chat-mode', 'agent')
  })
})
