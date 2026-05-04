import { useState, useCallback, useRef, useEffect } from 'react';
import { ChatMessage, ToolCall, WS_EVENT } from '../types';
import { useWebSocket } from './useWebSocket';
import { saveSession, loadSession, saveDraft, loadDraft, deleteDraft } from '../lib/db';

function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

export function useChatSession(sessionId: string, currentModel: string, roleId: string = 'desktop-agent') {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [isRunning, setIsRunning] = useState(false);

  // 用于外部监听 tool_call 事件做预览检测
  const onToolCallRef = useRef<((tc: ToolCall) => void) | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const addTerminalLog = useCallback((log: string) => {
    setTerminalLogs((prev) => [
      ...prev.slice(-200),
      `[${new Date().toLocaleTimeString()}] ${log}`,
    ]);
  }, []);

  const handleMessage = useCallback(
    (event: WS_EVENT) => {
      switch (event.type) {
        case 'content':
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === 'assistant' && !last.isTool) {
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...last,
                content: last.content + event.data.text,
                skill: event.data.skill || last.skill,
              };
              return updated;
            }
            return [
              ...prev,
              {
                id: generateId(),
                role: 'assistant',
                content: event.data.text,
                isTool: false,
                skill: event.data.skill,
              },
            ];
          });
          break;

        case 'reasoning':
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === 'assistant' && !last.isTool) {
              const updated = [...prev];
              updated[updated.length - 1] = {
                ...last,
                reasoning: (last.reasoning || '') + event.data.text,
                skill: event.data.skill || last.skill,
              };
              return updated;
            }
            return [
              ...prev,
              {
                id: generateId(),
                role: 'assistant',
                content: '',
                isTool: false,
                reasoning: event.data.text,
                skill: event.data.skill,
              },
            ];
          });
          break;

        case 'worker_start':
          setToolCalls((prev) => {
            const updated = [...prev];
            for (let i = updated.length - 1; i >= 0; i--) {
              if (updated[i].name === 'dispatch_worker' || updated[i].name === 'dispatch_parallel') {
                const existing = updated[i].workerEvents || [];
                updated[i] = {
                  ...updated[i],
                  workerEvents: [...existing, {
                    workerId: event.data.worker_id,
                    type: 'worker_start' as const,
                    status: 'running' as const,
                  }],
                };
                break;
              }
            }
            return updated;
          });
          break;

        case 'worker_content':
          setToolCalls((prev) => {
            const updated = [...prev];
            for (let i = updated.length - 1; i >= 0; i--) {
              if (updated[i].name === 'dispatch_worker' || updated[i].name === 'dispatch_parallel') {
                const existing = updated[i].workerEvents || [];
                updated[i] = {
                  ...updated[i],
                  workerEvents: [...existing, {
                    workerId: event.data.worker_id,
                    type: 'worker_content' as const,
                    text: event.data.text,
                  }],
                };
                break;
              }
            }
            return updated;
          });
          break;

        case 'worker_tool_call':
          setToolCalls((prev) => {
            const updated = [...prev];
            for (let i = updated.length - 1; i >= 0; i--) {
              if (updated[i].name === 'dispatch_worker' || updated[i].name === 'dispatch_parallel') {
                const existing = updated[i].workerEvents || [];
                updated[i] = {
                  ...updated[i],
                  workerEvents: [...existing, {
                    workerId: event.data.worker_id,
                    type: 'worker_tool_call' as const,
                    toolName: event.data.name,
                    toolArgs: event.data.args,
                    toolResult: event.data.result,
                    toolDurationMs: event.data.duration_ms,
                  }],
                };
                break;
              }
            }
            return updated;
          });
          addTerminalLog(`[Worker:${event.data.worker_id}] ${event.data.name}: ${event.data.result}`);
          break;

        case 'worker_done':
          setToolCalls((prev) => {
            const updated = [...prev];
            for (let i = updated.length - 1; i >= 0; i--) {
              if (updated[i].name === 'dispatch_worker' || updated[i].name === 'dispatch_parallel') {
                const existing = updated[i].workerEvents || [];
                updated[i] = {
                  ...updated[i],
                  workerEvents: [...existing, {
                    workerId: event.data.worker_id,
                    type: 'worker_done' as const,
                    status: event.data.status,
                    result: event.data.result,
                    iterations: event.data.iterations,
                    durationMs: event.data.duration_ms,
                  }],
                };
                break;
              }
            }
            return updated;
          });
          addTerminalLog(`[Worker:${event.data.worker_id}] Done (${event.data.status}, ${event.data.iterations} iterations)`);
          break;

        case 'tool_call': {
          const tc: ToolCall = {
            name: event.data.name,
            args: event.data.args,
            result: event.data.result,
            timestamp: Date.now(),
            runId: event.data.run_id,
            toolCallId: event.data.tool_call_id,
            durationMs: event.data.duration_ms,
          };
          setToolCalls((prev) => [...prev, tc]);
          // 工具调用不再显示在聊天面板，仅在右侧面板和终端显示
          addTerminalLog(`[工具] ${event.data.name}: ${event.data.result}`);
          onToolCallRef.current?.(tc);
          break;
        }

        case 'tool_result': {
          const resultText = event.data.error
            ? `[ERROR] ${event.data.error}`
            : event.data.output || '';
          const tc: ToolCall = {
            name: event.data.name,
            args: event.data.args || {},
            result: resultText,
            timestamp: Date.now(),
            runId: event.data.run_id,
            toolCallId: event.data.tool_call_id,
            durationMs: event.data.duration_ms,
          };
          setToolCalls((prev) => [...prev, tc]);
          addTerminalLog(`[å·¥å…·] ${event.data.name}: ${resultText}`);
          onToolCallRef.current?.(tc);
          if (event.data.image) {
            setMessages((prev) => [
              ...prev,
              {
                id: generateId(),
                role: 'assistant',
                content: '',
                imageBase64: event.data.image,
                isTool: false,
              },
            ]);
          }
          break;
        }

        case 'image':
          setMessages((prev) => [
            ...prev,
            {
              id: generateId(),
              role: 'assistant',
              content: '',
              imageBase64: event.data.base64,
              isTool: false,
            },
          ]);
          break;

        case 'status':
          if (
            event.data.status === 'completed' ||
            event.data.status === 'max_iterations_reached'
          ) {
            setIsRunning(false);
          }
          addTerminalLog(
            `[状态] ${event.data.status} (迭代: ${event.data.iteration})`
          );
          break;

        case 'error':
          setMessages((prev) => [
            ...prev,
            {
              id: generateId(),
              role: 'system',
              content: `错误: ${event.data.message}`,
              isTool: false,
            },
          ]);
          setIsRunning(false);
          addTerminalLog(`[错误] ${event.data.message}`);
          break;

        case 'done':
          setIsRunning(false);
          break;

        case 'cleared':
          setMessages([]);
          setToolCalls([]);
          addTerminalLog('[系统] 会话已清空');
          break;

        case 'interrupted':
          setIsRunning(false);
          addTerminalLog('[系统] 用户中断');
          break;
      }
    },
    [addTerminalLog]
  );

  const { isConnected, send, disconnect } = useWebSocket(sessionId, handleMessage);

  // 加载持久化数据
  useEffect(() => {
    let mounted = true;
    loadSession(sessionId).then((data) => {
      if (!mounted || !data) return;
      setMessages(data.messages || []);
      setToolCalls(data.toolCalls || []);
    });
    return () => { mounted = false; };
  }, [sessionId]);

  // 自动保存到 IndexedDB（debounce 1s）
  useEffect(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveSession(sessionId, messages, toolCalls).catch(console.error);
    }, 1000);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [sessionId, messages, toolCalls]);

  const sendMessage = useCallback(
    (text: string, imageBase64?: string) => {
      if (!text.trim() && !imageBase64) return;
      if (!currentModel) {
        addTerminalLog('[错误] 模型未加载，请等待页面加载完成');
        return;
      }
      setIsRunning(true);
      setMessages((prev) => [
        ...prev,
        {
          id: generateId(),
          role: 'user',
          content: text.trim(),
          imageBase64,
          isTool: false,
        },
      ]);
      const sent = send({
        type: 'chat',
        text: text.trim(),
        model_id: currentModel,
        role_id: roleId,
        image_base64: imageBase64,
      });
      if (sent === false) {
        setIsRunning(false);
        addTerminalLog('[é”™è¯¯] WebSocket æœªè¿žæŽ¥ï¼Œæ¶ˆæ¯æœªå‘é€');
      }
    },
    [send, currentModel, roleId, addTerminalLog]
  );

  const clearSession = useCallback(() => {
    send({ type: 'clear' });
  }, [send]);

  const stopRunning = useCallback(() => {
    send({ type: 'stop' });
  }, [send]);

  const retryLast = useCallback(() => {
    send({ type: 'retry', model_id: currentModel, role_id: roleId });
    setIsRunning(true);
  }, [send, currentModel, roleId]);

  const executeToolDirect = useCallback(
    (toolName: string, args: any) => {
      send({ type: 'tool_direct', tool_name: toolName, args });
    },
    [send]
  );

  const resetSession = useCallback(() => {
    disconnect();
    setMessages([]);
    setToolCalls([]);
    setTerminalLogs([]);
    setIsRunning(false);
  }, [disconnect]);

  const saveInputDraft = useCallback(async (text: string) => {
    await saveDraft(sessionId, text);
  }, [sessionId]);

  const loadInputDraft = useCallback(async (): Promise<string | undefined> => {
    return loadDraft(sessionId);
  }, [sessionId]);

  const clearInputDraft = useCallback(async () => {
    await deleteDraft(sessionId);
  }, [sessionId]);

  return {
    messages,
    toolCalls,
    terminalLogs,
    isRunning,
    isConnected,
    sendMessage,
    clearSession,
    stopRunning,
    retryLast,
    executeToolDirect,
    resetSession,
    addTerminalLog,
    onToolCallRef,
    saveInputDraft,
    loadInputDraft,
    clearInputDraft,
  };
}
