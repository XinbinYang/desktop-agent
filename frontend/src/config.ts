export const API_BASE = 'http://127.0.0.1:8765';
export const WS_BASE = 'ws://127.0.0.1:8765';
export const AUTH_HEADER = 'X-Desktop-Agent-Token';

let authToken = '';
let fetchPatched = false;

export function getAuthToken(): string {
  return authToken;
}

export function withAuthQuery(url: string): string {
  if (!authToken) return url;
  const parsed = new URL(url);
  parsed.searchParams.set('token', authToken);
  return parsed.toString();
}

export async function initApiAuth(): Promise<void> {
  try {
    const token = await window.electronAPI?.getAuthToken?.();
    authToken = token || '';
  } catch (error) {
    console.warn('Failed to load Desktop Agent auth token:', error);
    authToken = '';
  }
  patchFetch();
}

export function __setAuthTokenForTests(token: string): void {
  authToken = token;
}

function patchFetch(): void {
  if (fetchPatched || typeof window === 'undefined' || typeof window.fetch !== 'function') {
    return;
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = getFetchUrl(input);
    if (authToken && url?.startsWith(API_BASE)) {
      const headers = new Headers(init?.headers || getRequestHeaders(input));
      headers.set(AUTH_HEADER, authToken);
      return originalFetch(input, { ...init, headers });
    }
    return originalFetch(input, init);
  };
  fetchPatched = true;
}

function getFetchUrl(input: RequestInfo | URL): string | undefined {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  if (typeof Request !== 'undefined' && input instanceof Request) return input.url;
  return undefined;
}

function getRequestHeaders(input: RequestInfo | URL): HeadersInit | undefined {
  if (typeof Request !== 'undefined' && input instanceof Request) {
    return input.headers;
  }
  return undefined;
}
