export const API_BASE = 'http://127.0.0.1:8765';
export const WS_BASE = 'ws://127.0.0.1:8765';
export const AUTH_HEADER = 'X-Desktop-Agent-Token';

export type AuthRequirementStatus = 'unknown' | 'auth-required' | 'auth-disabled';

let authToken = '';
let fetchPatched = false;
let authUnavailableReason = '';
let authInitPromise: Promise<void> | null = null;
let authRequirementStatus: AuthRequirementStatus = 'unknown';

export function getAuthToken(): string {
  return authToken;
}

export function getAuthUnavailableReason(): string {
  return authUnavailableReason;
}

export function getAuthRequirementStatus(): AuthRequirementStatus {
  return authRequirementStatus;
}

export function withAuthQuery(url: string): string {
  if (!authToken) return url;
  const parsed = new URL(url);
  parsed.searchParams.set('token', authToken);
  return parsed.toString();
}

export async function initApiAuth(): Promise<void> {
  if (authInitPromise) {
    await authInitPromise;
    return;
  }
  authInitPromise = loadApiAuth();
  try {
    await authInitPromise;
  } finally {
    authInitPromise = null;
  }
}

export async function ensureApiAuth(): Promise<void> {
  if (authToken || authUnavailableReason || authInitPromise) {
    await authInitPromise;
    return;
  }
  if (typeof window !== 'undefined' && window.electronAPI?.getAuthToken) {
    await initApiAuth();
  }
}

async function loadApiAuth(): Promise<void> {
  authUnavailableReason = '';
  try {
    const token = await window.electronAPI?.getAuthToken?.();
    authToken = token || '';
  } catch (error) {
    console.warn('Failed to load Desktop Agent auth token:', error);
    authToken = '';
  }

  if (!authToken) {
    await refreshAuthRequirement();
  } else {
    authRequirementStatus = 'auth-required';
  }
  patchFetch();
}

export function __setAuthTokenForTests(token: string): void {
  authToken = token;
  authUnavailableReason = '';
  authInitPromise = null;
  authRequirementStatus = token ? 'auth-required' : 'unknown';
}

export async function refreshAuthRequirement(): Promise<AuthRequirementStatus> {
  authUnavailableReason = '';
  try {
    const res = await fetch(`${API_BASE}/api/health`, { cache: 'no-store' });
    if (res.status === 401 || res.status === 403) {
      const hasElectronAuthBridge = !!window.electronAPI?.getAuthToken;
      authRequirementStatus = 'auth-required';
      authUnavailableReason = hasElectronAuthBridge
        ? (authToken
          ? 'Desktop Agent local auth rejected the renderer token.'
          : 'Electron did not provide a Desktop Agent auth token.')
        : 'Desktop Agent local auth is enabled, but this page is not running inside Electron.';
      return authRequirementStatus;
    }
    if (res.status >= 200 && res.status < 400) {
      authRequirementStatus = 'auth-disabled';
      return authRequirementStatus;
    }
  } catch {
    // Backend may still be starting; keep the app bootable and let normal
    // reconnect behavior handle it.
  }
  authRequirementStatus = 'unknown';
  return authRequirementStatus;
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
