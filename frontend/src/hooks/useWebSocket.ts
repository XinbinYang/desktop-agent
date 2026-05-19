import { useState, useRef, useCallback, useEffect } from 'react';
import { WS_EVENT } from '../types';
import { ensureApiAuth, getAuthToken, getAuthUnavailableReason, refreshAuthRequirement, WS_BASE, withAuthQuery } from '../config';

const MAX_RECONNECT_DELAY = 30000;
const INITIAL_CONNECT_DELAY = 0;
const STOP_RECONNECT_CLOSE_CODES = new Set([1008, 4004]);
const QUIET_DROP_TYPES = new Set(["set_chat_mode", "set_team", "set_thinking_intensity"]);

function messageType(data: object): string {
  return typeof (data as { type?: unknown }).type === "string" ? (data as { type: string }).type : "";
}

export function useWebSocket(
  sessionId: string,
  onMessage: (msg: WS_EVENT) => void
) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempt = useRef(0);
  const onMessageRef = useRef(onMessage);
  const shouldReconnectRef = useRef(true);
  const connectRef = useRef<() => void>(() => {});

  const [isConnected, setIsConnected] = useState(false);

  // 保持回调引用最新，避免 ws 连接重建
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const scheduleReconnect = useCallback(() => {
    const delay = Math.min(1000 * 2 ** reconnectAttempt.current, MAX_RECONNECT_DELAY);
    reconnectAttempt.current += 1;
    reconnectTimer.current = setTimeout(connectRef.current, delay);
  }, []);

  const connect = useCallback(() => {
    const openWebSocket = () => {
      if (getAuthUnavailableReason()) {
        shouldReconnectRef.current = false;
        return;
      }
      if (!shouldReconnectRef.current) {
        return;
      }
      if (
        wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING
      ) {
        return;
      }

      shouldReconnectRef.current = true;

      const ws = new WebSocket(withAuthQuery(`${WS_BASE}/ws/${sessionId}`));
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        reconnectAttempt.current = 0;
      };

      ws.onmessage = (event) => {
        let msg: WS_EVENT;
        try {
          msg = JSON.parse(event.data);
        } catch (e) {
          console.error('Failed to parse WS message:', e);
          return;
        }

        try {
          onMessageRef.current(msg);
        } catch (e) {
          console.error('Failed to handle WS message:', e);
        }
      };

      ws.onclose = (event) => {
        if (wsRef.current !== ws) {
          return;
        }
        wsRef.current = null;
        setIsConnected(false);
        if (!shouldReconnectRef.current) {
          return;
        }
        if (event?.code !== 1000) {
          console.warn('WS closed:', { code: event?.code, reason: event?.reason, wasClean: event?.wasClean });
        }
        if (STOP_RECONNECT_CLOSE_CODES.has(event?.code)) {
          shouldReconnectRef.current = false;
          return;
        }
        if (event?.code === 1006) {
          refreshAuthRequirement().then(() => {
            if (!shouldReconnectRef.current) return;
            if (getAuthUnavailableReason()) {
              shouldReconnectRef.current = false;
              return;
            }
            scheduleReconnect();
          });
          return;
        }
        scheduleReconnect();
      };

      ws.onerror = (err) => {
        console.error('WS error:', err);
      };
    };

    const prepareAuthAndOpen = async () => {
      if (!getAuthToken() && !getAuthUnavailableReason()) {
        await ensureApiAuth();
      }
      if (!getAuthToken() && !getAuthUnavailableReason()) {
        await refreshAuthRequirement();
      }
      openWebSocket();
    };

    if (!getAuthToken() && !getAuthUnavailableReason()) {
      void prepareAuthAndOpen().catch((err) => {
        console.error('Failed to initialize WebSocket auth:', err);
        if (shouldReconnectRef.current) {
          scheduleReconnect();
        }
      });
      return;
    }

    openWebSocket();
  }, [scheduleReconnect, sessionId]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const send = useCallback((data: object): boolean => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
      return true;
    }
    const type = messageType(data);
    if (!QUIET_DROP_TYPES.has(type)) {
      console.warn('WebSocket is not connected; dropping message:', data);
    }
    return false;
  }, []);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    const ws = wsRef.current;
    wsRef.current = null;
    ws?.close();
    setIsConnected(false);
  }, []);

  useEffect(() => {
    shouldReconnectRef.current = true;
    const initialConnectTimer = setTimeout(connect, INITIAL_CONNECT_DELAY);
    return () => {
      clearTimeout(initialConnectTimer);
      disconnect();
    };
  }, [connect, disconnect]);

  return { isConnected, send, disconnect };
}
