import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { __resetSharedWebSocketsForTests, useWebSocket } from '../../hooks/useWebSocket'
import { __setAuthTokenForTests } from '../../config'
import type { WS_EVENT } from '../../types'

describe('useWebSocket', () => {
  let mockWsInstances: any[] = []
  let MockWebSocket: any

  beforeEach(() => {
    __resetSharedWebSocketsForTests()
    __setAuthTokenForTests('')
    delete (window as any).electronAPI
    mockWsInstances = []
    vi.spyOn(global, 'fetch').mockResolvedValue({ status: 200 } as Response)

    MockWebSocket = vi.fn(function (this: any, url: string | URL, protocols?: string | string[]) {
      const instance = {
        url,
        protocols,
        readyState: 0,
        send: vi.fn(),
        close: vi.fn(),
        onopen: null as any,
        onmessage: null as any,
        onclose: null as any,
        onerror: null as any,
      }
      mockWsInstances.push(instance)
      return instance
    }) as any

    MockWebSocket.CONNECTING = 0
    MockWebSocket.OPEN = 1
    MockWebSocket.CLOSING = 2
    MockWebSocket.CLOSED = 3
    global.WebSocket = MockWebSocket
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  const getLatestWs = () => mockWsInstances[mockWsInstances.length - 1]

  const waitForInitialConnect = async () => {
    await waitFor(() => {
      expect(MockWebSocket).toHaveBeenCalledTimes(1)
    })
    return getLatestWs()
  }

  it('connects to correct WebSocket URL', async () => {
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', onMessage))
    await waitForInitialConnect()
    expect(MockWebSocket).toHaveBeenCalledWith('ws://127.0.0.1:8765/ws/test-session')
  })

  it('appends auth token to WebSocket URL when configured', async () => {
    __setAuthTokenForTests('secret-token')
    const onMessage = vi.fn()

    renderHook(() => useWebSocket('test-session', onMessage))

    await waitForInitialConnect()
    expect(MockWebSocket).toHaveBeenCalledWith('ws://127.0.0.1:8765/ws/test-session?token=secret-token')
  })

  it('loads Electron auth token before connecting', async () => {
    ;(window as any).electronAPI = {
      getAuthToken: vi.fn().mockResolvedValue('late-token'),
    }
    const onMessage = vi.fn()

    renderHook(() => useWebSocket('test-session', onMessage))

    await waitForInitialConnect()
    expect((window as any).electronAPI.getAuthToken).toHaveBeenCalled()
    expect(MockWebSocket).toHaveBeenCalledWith('ws://127.0.0.1:8765/ws/test-session?token=late-token')
  })

  it('does not open an unauthenticated WebSocket when local auth is required', async () => {
    vi.mocked(global.fetch).mockResolvedValue({ status: 403 } as Response)
    const onMessage = vi.fn()

    renderHook(() => useWebSocket('test-session', onMessage))

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled()
    })
    expect(MockWebSocket).not.toHaveBeenCalled()
  })

  it('sets isConnected to true on open', async () => {
    const onMessage = vi.fn()
    const { result } = renderHook(() => useWebSocket('test-session', onMessage))

    const ws = await waitForInitialConnect()
    ws.readyState = 1
    ws.onopen?.()

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true)
    })
  })

  it('calls onMessage when receiving message', async () => {
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', onMessage))

    const ws = await waitForInitialConnect()
    const event: WS_EVENT = { type: 'content', data: { text: 'hello' } }
    ws.onmessage?.({ data: JSON.stringify(event) })

    await waitFor(() => {
      expect(onMessage).toHaveBeenCalledWith(event)
    })
  })

  it('sends data through websocket', async () => {
    const onMessage = vi.fn()
    const { result } = renderHook(() => useWebSocket('test-session', onMessage))

    const ws = await waitForInitialConnect()
    ws.readyState = 1
    result.current.send({ type: 'chat', text: 'hi' })

    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: 'chat', text: 'hi' }))
  })

  it('returns false when sending while disconnected', async () => {
    const onMessage = vi.fn()
    const { result } = renderHook(() => useWebSocket('test-session', onMessage))

    const ws = await waitForInitialConnect()
    ws.readyState = 3

    expect(result.current.send({ type: 'chat', text: 'hi' })).toBe(false)
    expect(ws.send).not.toHaveBeenCalled()
  })

  it('reconnects with exponential backoff on close', async () => {
    vi.useFakeTimers()
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', onMessage))
    await vi.runOnlyPendingTimersAsync()

    expect(MockWebSocket).toHaveBeenCalledTimes(1)

    const ws = getLatestWs()
    ws.onclose?.()

    // First reconnect after 1s
    await vi.advanceTimersByTimeAsync(1000)
    expect(MockWebSocket).toHaveBeenCalledTimes(2)

    // Second reconnect after 2s
    const ws2 = getLatestWs()
    ws2.onclose?.()
    await vi.advanceTimersByTimeAsync(2000)
    expect(MockWebSocket).toHaveBeenCalledTimes(3)
    vi.useRealTimers()
  })

  it('does not reconnect after explicit disconnect', async () => {
    vi.useFakeTimers()
    const onMessage = vi.fn()
    const { result } = renderHook(() => useWebSocket('test-session', onMessage))
    await vi.runOnlyPendingTimersAsync()

    const ws = getLatestWs()
    result.current.disconnect()
    ws.onclose?.()
    await vi.advanceTimersByTimeAsync(30000)

    expect(MockWebSocket).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('reuses a live socket across a quick same-session remount', async () => {
    vi.useFakeTimers()
    const onMessage = vi.fn()
    const { unmount } = renderHook(() => useWebSocket('test-session', onMessage))
    await vi.runOnlyPendingTimersAsync()

    const ws = getLatestWs()
    ws.readyState = 1
    ws.onopen?.()

    unmount()
    expect(ws.close).not.toHaveBeenCalled()

    const nextMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', nextMessage))
    await vi.runOnlyPendingTimersAsync()

    expect(MockWebSocket).toHaveBeenCalledTimes(1)
    expect(ws.close).not.toHaveBeenCalled()

    const event: WS_EVENT = { type: 'content', data: { text: 'still here' } }
    ws.onmessage?.({ data: JSON.stringify(event) })
    expect(onMessage).not.toHaveBeenCalled()
    expect(nextMessage).toHaveBeenCalledWith(event)

    vi.useRealTimers()
  })

  it('does not reconnect when the backend closes a deleted session', async () => {
    vi.useFakeTimers()
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('deleted-session', onMessage))
    await vi.runOnlyPendingTimersAsync()

    const ws = getLatestWs()
    ws.onclose?.({ code: 4004, reason: 'Session deleted', wasClean: true } as CloseEvent)
    await vi.advanceTimersByTimeAsync(30000)

    expect(MockWebSocket).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('stops reconnecting after an abnormal close reveals auth is required', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.mocked(global.fetch)
    fetchMock
      .mockResolvedValueOnce({ status: 200 } as Response)
      .mockResolvedValueOnce({ status: 403 } as Response)
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', onMessage))
    await vi.runOnlyPendingTimersAsync()

    const ws = getLatestWs()
    ws.onclose?.({ code: 1006, reason: '', wasClean: false } as CloseEvent)

    await Promise.resolve()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(30000)

    expect(MockWebSocket).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('ignores close events from stale sockets', async () => {
    const onMessage = vi.fn()
    const { result, rerender } = renderHook(
      ({ sessionId }) => useWebSocket(sessionId, onMessage),
      { initialProps: { sessionId: 'test-session-1' } },
    )

    const first = await waitForInitialConnect()
    first.readyState = 1
    first.onopen?.()

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true)
    })

    rerender({ sessionId: 'test-session-2' })
    await waitFor(() => {
      expect(MockWebSocket).toHaveBeenCalledTimes(2)
    })
    const second = getLatestWs()
    second.readyState = 1
    second.onopen?.()

    first.onclose?.({ code: 1006, reason: '', wasClean: false } as CloseEvent)

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true)
    })
    expect(MockWebSocket).toHaveBeenCalledTimes(2)
  })
})
