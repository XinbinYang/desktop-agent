import '@testing-library/jest-dom'

// Mock WebSocket for tests
global.WebSocket = class MockWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  readyState = MockWebSocket.OPEN
  onopen: ((this: WebSocket, ev: Event) => any) | null = null
  onmessage: ((this: WebSocket, ev: MessageEvent) => any) | null = null
  onclose: ((this: WebSocket, ev: CloseEvent) => any) | null = null
  onerror: ((this: WebSocket, ev: Event) => any) | null = null

  constructor(public url: string | URL, protocols?: string | string[]) {}

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView) {}
  close(code?: number, reason?: string) {}
} as any
