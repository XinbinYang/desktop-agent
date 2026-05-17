import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useChatSession } from '../../hooks/useChatSession'
import type { WS_EVENT } from '../../types'

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

  it('handles content event by appending to assistant message', async () => {
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

    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].blocks).toBeDefined()
    expect(result.current.messages[0].blocks![0].type).toBe('text')
    expect((result.current.messages[0].blocks![0] as { text: string }).text).toBe('Hello')

    // Second content event merges into the same text block
    act(() => {
      messageHandler?.({ type: 'content', data: { text: ' world' } })
    })

    // Re-read blocks from the updated state (not stale reference)
    expect(result.current.messages[0].blocks![0].type).toBe('text')
    expect((result.current.messages[0].blocks![0] as { text: string }).text).toBe('Hello world')
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

  it('setThinkingIntensity sends set_thinking_intensity to the server', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.setThinkingIntensity('high')
    })

    expect(result.current.thinkingIntensity).toBe('high')
    expect(mockSend).toHaveBeenCalledWith({ type: 'set_thinking_intensity', thinking_intensity: 'high' })
  })

  it('sends compact and rewind session control messages', () => {
    const { result } = renderHook(() => useChatSession('session-1', 'gpt-4o'))

    act(() => {
      result.current.compactSession(false)
      result.current.rewindToCheckpoint('chk_1')
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
