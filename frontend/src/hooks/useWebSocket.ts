import { useState, useRef, useCallback, useEffect } from 'react';
import { WS_EVENT } from '../types';
import { ensureApiAuth, getAuthToken, getAuthUnavailableReason, refreshAuthRequirement, WS_BASE, withAuthQuery } from '../config';

const MAX_RECONNECT_DELAY = 30000;
const INITIAL_CONNECT_DELAY = 0;
const IDLE_RELEASE_DELAY = 300;
const STOP_RECONNECT_CLOSE_CODES = new Set([1008, 4004]);
const QUIET_DROP_TYPES = new Set(['set_chat_mode', 'set_team', 'set_thinking_intensity']);

function messageType(data: object): string {
  return typeof (data as { type?: unknown }).type === 'string' ? (data as { type: string }).type : '';
}

type MessageSubscriber = (msg: WS_EVENT) => void;
type ConnectionSubscriber = (connected: boolean) => void;

interface SharedSocketEntry {
  sessionId: string;
  ws: WebSocket | null;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  releaseTimer: ReturnType<typeof setTimeout> | null;
  reconnectAttempt: number;
  shouldReconnect: boolean;
  authInFlight: boolean;
  messageSubscribers: Set<MessageSubscriber>;
  connectionSubscribers: Set<ConnectionSubscriber>;
}

const sharedSockets = new Map<string, SharedSocketEntry>();

export function __resetSharedWebSocketsForTests() {
  for (const entry of Array.from(sharedSockets.values())) {
    if (entry.releaseTimer) clearTimeout(entry.releaseTimer);
    clearReconnectTimer(entry);
    entry.shouldReconnect = false;
    const ws = entry.ws;
    entry.ws = null;
    ws?.close();
  }
  sharedSockets.clear();
}

function notifyConnection(entry: SharedSocketEntry, connected: boolean) {
  for (const subscriber of Array.from(entry.connectionSubscribers)) {
    subscriber(connected);
  }
}

function clearReconnectTimer(entry: SharedSocketEntry) {
  if (entry.reconnectTimer) {
    clearTimeout(entry.reconnectTimer);
    entry.reconnectTimer = null;
  }
}

function scheduleReconnect(entry: SharedSocketEntry) {
  if (entry.messageSubscribers.size === 0 || !entry.shouldReconnect) return;
  clearReconnectTimer(entry);
  const delay = Math.min(1000 * 2 ** entry.reconnectAttempt, MAX_RECONNECT_DELAY);
  entry.reconnectAttempt += 1;
  entry.reconnectTimer = setTimeout(() => connectEntry(entry), delay);
}

function openWebSocket(entry: SharedSocketEntry) {
  if (sharedSockets.get(entry.sessionId) !== entry) return;
  if (getAuthUnavailableReason()) {
    entry.shouldReconnect = false;
    return;
  }
  if (!entry.shouldReconnect || entry.messageSubscribers.size === 0) return;
  if (
    entry.ws?.readyState === WebSocket.OPEN ||
    entry.ws?.readyState === WebSocket.CONNECTING
  ) {
    return;
  }

  const ws = new WebSocket(withAuthQuery(`${WS_BASE}/ws/${entry.sessionId}`));
  entry.ws = ws;

  ws.onopen = () => {
    if (entry.ws !== ws) return;
    entry.reconnectAttempt = 0;
    notifyConnection(entry, true);
  };

  ws.onmessage = (event) => {
    let msg: WS_EVENT;
    try {
      msg = JSON.parse(event.data);
    } catch (e) {
      console.error('Failed to parse WS message:', e);
      return;
    }

    for (const subscriber of Array.from(entry.messageSubscribers)) {
      subscriber(msg);
    }
  };

  ws.onclose = (event) => {
    if (entry.ws !== ws) return;
    entry.ws = null;
    notifyConnection(entry, false);
    if (!entry.shouldReconnect || entry.messageSubscribers.size === 0) return;
    if (event?.code !== 1000) {
      console.warn('WS closed:', { code: event?.code, reason: event?.reason, wasClean: event?.wasClean });
    }
    if (typeof event?.code === 'number' && STOP_RECONNECT_CLOSE_CODES.has(event.code)) {
      entry.shouldReconnect = false;
      return;
    }
    if (event?.code === 1006) {
      refreshAuthRequirement().then(() => {
        if (!entry.shouldReconnect || entry.messageSubscribers.size === 0) return;
        if (getAuthUnavailableReason()) {
          entry.shouldReconnect = false;
          return;
        }
        scheduleReconnect(entry);
      });
      return;
    }
    scheduleReconnect(entry);
  };

  ws.onerror = (err) => {
    console.error('WS error:', err);
  };
}

function connectEntry(entry: SharedSocketEntry) {
  if (entry.messageSubscribers.size === 0 || !entry.shouldReconnect) return;

  const prepareAuthAndOpen = async () => {
    try {
      if (!getAuthToken() && !getAuthUnavailableReason()) {
        await ensureApiAuth();
      }
      if (!getAuthToken() && !getAuthUnavailableReason()) {
        await refreshAuthRequirement();
      }
      openWebSocket(entry);
    } catch (err) {
      console.error('Failed to initialize WebSocket auth:', err);
      if (entry.shouldReconnect && entry.messageSubscribers.size > 0) {
        scheduleReconnect(entry);
      }
    } finally {
      entry.authInFlight = false;
    }
  };

  if (!getAuthToken() && !getAuthUnavailableReason()) {
    if (entry.authInFlight) return;
    entry.authInFlight = true;
    void prepareAuthAndOpen();
    return;
  }

  openWebSocket(entry);
}

function getSharedSocketEntry(sessionId: string): SharedSocketEntry {
  let entry = sharedSockets.get(sessionId);
  if (!entry) {
    entry = {
      sessionId,
      ws: null,
      reconnectTimer: null,
      releaseTimer: null,
      reconnectAttempt: 0,
      shouldReconnect: true,
      authInFlight: false,
      messageSubscribers: new Set(),
      connectionSubscribers: new Set(),
    };
    sharedSockets.set(sessionId, entry);
  }
  return entry;
}

function retainSocket(
  sessionId: string,
  onMessage: MessageSubscriber,
  onConnection: ConnectionSubscriber,
): SharedSocketEntry {
  const entry = getSharedSocketEntry(sessionId);
  if (entry.releaseTimer) {
    clearTimeout(entry.releaseTimer);
    entry.releaseTimer = null;
  }
  clearReconnectTimer(entry);
  entry.shouldReconnect = true;
  entry.messageSubscribers.add(onMessage);
  entry.connectionSubscribers.add(onConnection);
  onConnection(entry.ws?.readyState === WebSocket.OPEN);
  entry.reconnectTimer = setTimeout(() => connectEntry(entry), INITIAL_CONNECT_DELAY);
  return entry;
}

function releaseSocket(
  entry: SharedSocketEntry,
  onMessage: MessageSubscriber,
  onConnection: ConnectionSubscriber,
  immediate: boolean,
) {
  entry.messageSubscribers.delete(onMessage);
  entry.connectionSubscribers.delete(onConnection);
  onConnection(false);

  if (entry.messageSubscribers.size > 0) return;

  const closeIfIdle = () => {
    entry.releaseTimer = null;
    if (entry.messageSubscribers.size > 0) return;
    entry.shouldReconnect = false;
    clearReconnectTimer(entry);
    const ws = entry.ws;
    entry.ws = null;
    sharedSockets.delete(entry.sessionId);
    ws?.close();
  };

  if (entry.releaseTimer) {
    clearTimeout(entry.releaseTimer);
    entry.releaseTimer = null;
  }

  if (immediate) {
    closeIfIdle();
  } else {
    entry.releaseTimer = setTimeout(closeIfIdle, IDLE_RELEASE_DELAY);
  }
}

export function useWebSocket(
  sessionId: string,
  onMessage: (msg: WS_EVENT) => void,
) {
  const onMessageRef = useRef(onMessage);
  const entryRef = useRef<SharedSocketEntry | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const handleSharedMessage = useCallback((msg: WS_EVENT) => {
    try {
      onMessageRef.current(msg);
    } catch (e) {
      console.error('Failed to handle WS message:', e);
    }
  }, []);

  const send = useCallback((data: object): boolean => {
    const entry = entryRef.current || sharedSockets.get(sessionId);
    if (entry?.ws?.readyState === WebSocket.OPEN) {
      entry.ws.send(JSON.stringify(data));
      return true;
    }
    const type = messageType(data);
    if (!QUIET_DROP_TYPES.has(type)) {
      console.warn('WebSocket is not connected; dropping message:', data);
    }
    return false;
  }, [sessionId]);

  const disconnect = useCallback(() => {
    const entry = entryRef.current || sharedSockets.get(sessionId);
    if (entry) {
      releaseSocket(entry, handleSharedMessage, setIsConnected, true);
      if (entryRef.current === entry) entryRef.current = null;
    }
    setIsConnected(false);
  }, [handleSharedMessage, sessionId]);

  useEffect(() => {
    const entry = retainSocket(sessionId, handleSharedMessage, setIsConnected);
    entryRef.current = entry;
    return () => {
      releaseSocket(entry, handleSharedMessage, setIsConnected, false);
      if (entryRef.current === entry) entryRef.current = null;
    };
  }, [handleSharedMessage, sessionId]);

  return { isConnected, send, disconnect };
}
