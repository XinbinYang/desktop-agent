import { describe, it, expect } from 'vitest'
import { API_BASE, WS_BASE, __setAuthTokenForTests, withAuthQuery } from '../config'

describe('config', () => {
  it('should have correct API base URL', () => {
    expect(API_BASE).toBe('http://127.0.0.1:8765')
  })

  it('should have correct WebSocket base URL', () => {
    expect(WS_BASE).toBe('ws://127.0.0.1:8765')
  })

  it('adds auth token as query param when configured', () => {
    __setAuthTokenForTests('abc123')
    expect(withAuthQuery(`${WS_BASE}/ws/session`)).toBe(`${WS_BASE}/ws/session?token=abc123`)
    __setAuthTokenForTests('')
  })
})
