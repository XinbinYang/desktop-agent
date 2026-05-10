import { useState, useRef, useCallback, useEffect } from 'react';
import { WS_EVENT } from '../types';
import { WS_BASE, withAuthQuery } from '../config';

const MAX_RECONNECT_DELAY = 30000;

export function useWebSocket(
  sessionId: string,
  onMessage: (msg: WS_EVENT) => void
) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempt = useRef(0);
  const onMessageRef = useRef(onMessage);
  const shouldReconnectRef = useRef(true);

  const [isConnected, setIsConnected] = useState(false);

  // 保持回调引用最新，避免 ws 连接重建
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  const connect = useCallback(() => {
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
      try {
        const msg: WS_EVENT = JSON.parse(event.data);
        onMessageRef.current(msg);
      } catch (e) {
        console.error('Failed to parse WS message:', e);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      if (!shouldReconnectRef.current || wsRef.current !== ws) {
        return;
      }
      wsRef.current = null;
      const delay = Math.min(1000 * 2 ** reconnectAttempt.current, MAX_RECONNECT_DELAY);
      reconnectAttempt.current += 1;
      reconnectTimer.current = setTimeout(connect, delay);
    };

    ws.onerror = (err) => {
      console.error('WS error:', err);
    };
  }, [sessionId]);

  const send = useCallback((data: object): boolean => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
      return true;
    }
    console.warn('WebSocket is not connected; dropping message:', data);
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
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { isConnected, send, disconnect };
}
