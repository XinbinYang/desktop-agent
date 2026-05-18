import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useWebSocket } from '../../hooks/useWebSocket'
import { __setAuthTokenForTests } from '../../config'
import type { WS_EVENT } from '../../types'

describe('useWebSocket', () => {
  let mockWsInstances: any[] = []
  let MockWebSocket: any

  beforeEach(() => {
    __setAuthTokenForTests('')
    delete (window as any).electronAPI
    mockWsInstances = []

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

  it('reconnects with exponential backoff on close', () => {
    vi.useFakeTimers()
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', onMessage))
    vi.runOnlyPendingTimers()

    expect(MockWebSocket).toHaveBeenCalledTimes(1)

    const ws = getLatestWs()
    ws.onclose?.()

    // First reconnect after 1s
    vi.advanceTimersByTime(1000)
    expect(MockWebSocket).toHaveBeenCalledTimes(2)

    // Second reconnect after 2s
    const ws2 = getLatestWs()
    ws2.onclose?.()
    vi.advanceTimersByTime(2000)
    expect(MockWebSocket).toHaveBeenCalledTimes(3)
    vi.useRealTimers()
  })

  it('does not reconnect after explicit disconnect', () => {
    vi.useFakeTimers()
    const onMessage = vi.fn()
    const { result } = renderHook(() => useWebSocket('test-session', onMessage))
    vi.runOnlyPendingTimers()

    const ws = getLatestWs()
    result.current.disconnect()
    ws.onclose?.()
    vi.advanceTimersByTime(30000)

    expect(MockWebSocket).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('does not reconnect when the backend closes a deleted session', () => {
    vi.useFakeTimers()
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('deleted-session', onMessage))
    vi.runOnlyPendingTimers()

    const ws = getLatestWs()
    ws.onclose?.({ code: 4004, reason: 'Session deleted', wasClean: true } as CloseEvent)
    vi.advanceTimersByTime(30000)

    expect(MockWebSocket).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('stops reconnecting after an abnormal close reveals auth is required', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue({ status: 403 } as Response)
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', onMessage))
    vi.runOnlyPendingTimers()

    const ws = getLatestWs()
    ws.onclose?.({ code: 1006, reason: '', wasClean: false } as CloseEvent)

    await Promise.resolve()
    expect(fetchMock).toHaveBeenCalled()
    await Promise.resolve()
    vi.advanceTimersByTime(30000)

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
