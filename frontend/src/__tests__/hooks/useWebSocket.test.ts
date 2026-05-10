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
  })

  const getLatestWs = () => mockWsInstances[mockWsInstances.length - 1]

  it('connects to correct WebSocket URL', () => {
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', onMessage))
    expect(MockWebSocket).toHaveBeenCalledWith('ws://127.0.0.1:8765/ws/test-session')
  })

  it('appends auth token to WebSocket URL when configured', () => {
    __setAuthTokenForTests('secret-token')
    const onMessage = vi.fn()

    renderHook(() => useWebSocket('test-session', onMessage))

    expect(MockWebSocket).toHaveBeenCalledWith('ws://127.0.0.1:8765/ws/test-session?token=secret-token')
  })

  it('sets isConnected to true on open', async () => {
    const onMessage = vi.fn()
    const { result } = renderHook(() => useWebSocket('test-session', onMessage))

    const ws = getLatestWs()
    ws.readyState = 1
    ws.onopen?.()

    await waitFor(() => {
      expect(result.current.isConnected).toBe(true)
    })
  })

  it('calls onMessage when receiving message', async () => {
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', onMessage))

    const ws = getLatestWs()
    const event: WS_EVENT = { type: 'content', data: { text: 'hello' } }
    ws.onmessage?.({ data: JSON.stringify(event) })

    await waitFor(() => {
      expect(onMessage).toHaveBeenCalledWith(event)
    })
  })

  it('sends data through websocket', () => {
    const onMessage = vi.fn()
    const { result } = renderHook(() => useWebSocket('test-session', onMessage))

    const ws = getLatestWs()
    ws.readyState = 1
    result.current.send({ type: 'chat', text: 'hi' })

    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: 'chat', text: 'hi' }))
  })

  it('returns false when sending while disconnected', () => {
    const onMessage = vi.fn()
    const { result } = renderHook(() => useWebSocket('test-session', onMessage))

    const ws = getLatestWs()
    ws.readyState = 3

    expect(result.current.send({ type: 'chat', text: 'hi' })).toBe(false)
    expect(ws.send).not.toHaveBeenCalled()
  })

  it('reconnects with exponential backoff on close', () => {
    vi.useFakeTimers()
    const onMessage = vi.fn()
    renderHook(() => useWebSocket('test-session', onMessage))

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

    const ws = getLatestWs()
    result.current.disconnect()
    ws.onclose?.()
    vi.advanceTimersByTime(30000)

    expect(MockWebSocket).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })
})
