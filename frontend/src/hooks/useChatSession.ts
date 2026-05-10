import { useState, useCallback, useRef, useEffect } from 'react';
import { ChatMessage, ToolCall, AssistantBlock, WS_EVENT, WorkerEvent, FileEdit } from '../types';
import { useWebSocket } from './useWebSocket';
import { saveSession, loadSession, saveDraft, loadDraft, deleteDraft } from '../lib/db';

function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function appendBlock(
  messages: ChatMessage[],
  block: AssistantBlock,
  mergeable: boolean,
): ChatMessage[] {
  const updated = [...messages];
  const last = updated[updated.length - 1];

  if (last && last.role === 'assistant' && !last.turnComplete) {
    const blocks = [...(last.blocks || [])];
    if (mergeable && blocks.length > 0) {
      const lastBlock = blocks[blocks.length - 1];
      if (lastBlock.type === block.type && (lastBlock.type === 'thinking' || lastBlock.type === 'text')) {
        blocks[blocks.length - 1] = {
          ...lastBlock,
          text: (lastBlock as { text: string }).text + (block as { text: string }).text,
        } as AssistantBlock;
        updated[updated.length - 1] = { ...last, blocks };
        return updated;
      }
    }
    updated[updated.length - 1] = { ...last, blocks: [...blocks, block] };
  } else {
    updated.push({
      id: generateId(),
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [block],
      turnComplete: false,
    });
  }
  return updated;
}

function markTurnComplete(messages: ChatMessage[]): ChatMessage[] {
  const updated = [...messages];
  const last = updated[updated.length - 1];
  if (last && last.role === 'assistant') {
    updated[updated.length - 1] = { ...last, turnComplete: true };
  }
  return updated;
}

function mergeBlock(
  messages: ChatMessage[],
  predicate: (b: AssistantBlock) => boolean,
  merge: (b: AssistantBlock) => AssistantBlock,
): ChatMessage[] | null {
  const updated = [...messages];
  for (let mi = updated.length - 1; mi >= 0; mi--) {
    const msg = updated[mi];
    if (msg.role !== 'assistant' || !msg.blocks) continue;
    const blocks = msg.blocks;
    for (let bi = blocks.length - 1; bi >= 0; bi--) {
      if (predicate(blocks[bi])) {
        const newBlocks = [...blocks];
        newBlocks[bi] = merge(newBlocks[bi]);
        updated[mi] = { ...msg, blocks: newBlocks };
        return updated;
      }
    }
  }
  return null;
}

function isDispatchTool(name?: string): boolean {
  return name === 'dispatch_worker' || name === 'dispatch_parallel';
}

function toWorkerEvent(event: WS_EVENT): WorkerEvent {
  return {
    workerId: event.data.worker_id,
    type: event.type as WorkerEvent['type'],
    task: event.data.task,
    profile: event.data.profile,
    modelId: event.data.model_id,
    runId: event.data.run_id,
    parentToolCallId: event.data.parent_tool_call_id,
    text: event.data.text,
    toolName: event.data.name,
    toolArgs: event.data.args,
    toolResult: event.data.result,
    toolDurationMs: event.data.duration_ms,
    status: event.data.status,
    result: event.data.result,
    iterations: event.data.iterations,
    durationMs: event.data.duration_ms,
  };
}

function mergeWorkerEvents(existing: WorkerEvent[] = [], incoming: WorkerEvent[] = []): WorkerEvent[] {
  const merged = [...existing];
  for (const event of incoming) {
    const duplicate = merged.some((item) =>
      item.workerId === event.workerId &&
      item.type === event.type &&
      item.parentToolCallId === event.parentToolCallId &&
      item.task === event.task &&
      item.text === event.text &&
      item.toolName === event.toolName &&
      item.result === event.result
    );
    if (!duplicate) merged.push(event);
  }
  return merged;
}

export function useChatSession(sessionId: string, currentModel: string, roleId: string = 'desktop-agent') {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [fileEdits, setFileEdits] = useState<FileEdit[]>([]);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [isRunning, setIsRunning] = useState(false);

  const onToolCallRef = useRef<((tc: ToolCall) => void) | null>(null);
  const onFileEditRef = useRef<((edit: FileEdit) => void) | null>(null);
  const pendingWorkerEventsRef = useRef<Record<string, WorkerEvent[]>>({});
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const addTerminalLog = useCallback((log: string) => {
    setTerminalLogs((prev) => [
      ...prev.slice(-200),
      `[${new Date().toLocaleTimeString()}] ${log}`,
    ]);
  }, []);

  const takePendingWorkerEvents = useCallback((toolCallId?: string): WorkerEvent[] => {
    const pending = pendingWorkerEventsRef.current;
    const events = [
      ...(toolCallId ? pending[toolCallId] || [] : []),
      ...(pending.__latest__ || []),
    ];
    if (toolCallId) delete pending[toolCallId];
    delete pending.__latest__;
    return events;
  }, []);

  const attachWorkerEvent = useCallback((workerEvent: WorkerEvent) => {
    const parentId = workerEvent.parentToolCallId;
    let attachedToTool = false;

    setToolCalls((prev) => {
      const updated = [...prev];
      for (let i = updated.length - 1; i >= 0; i--) {
        const matchesParent = parentId && updated[i].toolCallId === parentId;
        const matchesFallback = !parentId && isDispatchTool(updated[i].name);
        if (matchesParent || matchesFallback) {
          const existing = updated[i].workerEvents || [];
          updated[i] = { ...updated[i], workerEvents: [...existing, workerEvent] };
          attachedToTool = true;
          return updated;
        }
      }
      return prev;
    });

    setMessages((prev) => {
      const withUpdate = mergeBlock(
        prev,
        (b) =>
          b.type === 'tool_call' &&
          (parentId ? b.toolCallId === parentId : isDispatchTool(b.name)),
        (b) => ({
          ...b,
          workerEvents: [...((b as any).workerEvents || []), workerEvent],
        } as AssistantBlock),
      );
      return withUpdate || prev;
    });

    if (!attachedToTool) {
      const key = parentId || '__latest__';
      const pending = pendingWorkerEventsRef.current[key] || [];
      pendingWorkerEventsRef.current[key] = [...pending, workerEvent];
    }
  }, []);

  const recordFileEdit = useCallback((edit: FileEdit, appendToChat = false) => {
    const normalized = {
      ...edit,
      timestamp: edit.timestamp || Date.now(),
    };
    setFileEdits((prev) => [...prev, normalized]);
    if (appendToChat) {
      setMessages((prev) =>
        appendBlock(
          prev,
          { type: 'file_edit', edit: normalized, timestamp: Date.now() },
          false,
        ),
      );
    }
    addTerminalLog(`[Edit] ${normalized.path} (+${normalized.stats?.added || 0}/-${normalized.stats?.removed || 0})`);
    onFileEditRef.current?.(normalized);
  }, [addTerminalLog]);

  const handleMessage = useCallback(
    (event: WS_EVENT) => {
      switch (event.type) {
        case 'content':
          setMessages((prev) => {
            const updated = appendBlock(
              prev,
              { type: 'text', text: event.data.text, timestamp: Date.now() },
              true,
            );
            return updated;
          });
          break;

        case 'reasoning':
          setMessages((prev) =>
            appendBlock(
              prev,
              { type: 'thinking', text: event.data.text, timestamp: Date.now() },
              true,
            ),
          );
          break;

        case 'worker_start':
        case 'worker_content':
        case 'worker_tool_call':
        case 'worker_done': {
          const workerEvent = toWorkerEvent(event);
          attachWorkerEvent(workerEvent);
          if (event.type === 'worker_tool_call') {
            addTerminalLog(`[Worker:${event.data.worker_id}] ${event.data.name}: ${event.data.result}`);
          } else if (event.type === 'worker_done') {
            addTerminalLog(`[Worker:${event.data.worker_id}] Done (${event.data.status}, ${event.data.iterations} iterations)`);
          }
          break;
        }

        case 'tool_call': {
          const isError = (event.data.result || '').startsWith('[ERROR]');
          const workerEvents = isDispatchTool(event.data.name)
            ? takePendingWorkerEvents(event.data.tool_call_id)
            : undefined;
          const tc: ToolCall = {
            name: event.data.name,
            args: event.data.args,
            result: event.data.result,
            timestamp: Date.now(),
            runId: event.data.run_id,
            toolCallId: event.data.tool_call_id,
            durationMs: event.data.duration_ms,
            workerEvents,
          };
          setToolCalls((prev) => [...prev, tc]);
          addTerminalLog(`[工具] ${event.data.name}: ${event.data.result}`);
          onToolCallRef.current?.(tc);

          setMessages((prev) => {
            // Try to find and update a running placeholder created by status:executing
            const withUpdate = mergeBlock(
              prev,
              (b) =>
                b.type === 'tool_call' &&
                b.status === 'running' &&
                b.toolCallId === event.data.tool_call_id,
              (b) => ({
                ...b,
                name: event.data.name,
                args: event.data.args,
                result: event.data.result,
                status: isError ? 'error' as const : 'success' as const,
                durationMs: event.data.duration_ms,
                workerEvents: mergeWorkerEvents(
                  ((b as any).workerEvents as WorkerEvent[] | undefined) || [],
                  workerEvents || [],
                ),
              }),
            );
            if (withUpdate) return withUpdate;
            return appendBlock(
              prev,
              {
                type: 'tool_call',
                name: event.data.name,
                args: event.data.args,
                result: event.data.result,
                status: isError ? 'error' : 'success',
                toolCallId: event.data.tool_call_id,
                durationMs: event.data.duration_ms,
                workerEvents,
                timestamp: Date.now(),
              },
              false,
            );
          });
          break;
        }

        case 'tool_result': {
          const isError = !!event.data.error;
          const resultText = isError
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
          addTerminalLog(`[工具] ${event.data.name}: ${resultText}`);
          onToolCallRef.current?.(tc);

          setMessages((prev) =>
            appendBlock(
              prev,
              {
                type: 'tool_call',
                name: event.data.name,
                args: event.data.args || {},
                result: resultText,
                status: isError ? 'error' : 'success',
                toolCallId: event.data.tool_call_id,
                durationMs: event.data.duration_ms,
                timestamp: Date.now(),
              },
              false,
            ),
          );

          if (event.data.image) {
            setMessages((prev) =>
              appendBlock(
                prev,
                { type: 'image', base64: event.data.image, timestamp: Date.now() },
                false,
              ),
            );
          }
          break;
        }

        case 'image':
          setMessages((prev) =>
            appendBlock(
              prev,
              { type: 'image', base64: event.data.base64, timestamp: Date.now() },
              false,
            ),
          );
          break;

        case 'file_edit': {
          recordFileEdit(event.data as FileEdit, true);
          break;
        }

        case 'status': {
          const status = event.data.status;
          if (status === 'executing') {
            // Push a running placeholder — the matching tool_call event will fill in details
            setMessages((prev) =>
              appendBlock(
                prev,
                {
                  type: 'tool_call',
                  name: event.data.tool || '',
                  args: {},
                  status: 'running',
                  toolCallId: event.data.tool_call_id,
                  timestamp: Date.now(),
                },
                false,
              ),
            );
          } else if (status === 'completed' || status === 'max_iterations_reached') {
            setIsRunning(false);
            setMessages((prev) => markTurnComplete(prev));
          } else if (status === 'thinking') {
            // Start of new iteration — no new block needed; reasoning follows as its own block
          }
          addTerminalLog(
            `[状态] ${event.data.status} (迭代: ${event.data.iteration})`
          );
          break;
        }

        case 'error':
          setMessages((prev) => {
            const complete = markTurnComplete(prev);
            return [
              ...complete,
              {
                id: generateId(),
                role: 'system',
                content: `错误: ${event.data.message}`,
                isTool: false,
              },
            ];
          });
          setIsRunning(false);
          addTerminalLog(`[错误] ${event.data.message}`);
          break;

        case 'done':
          setIsRunning(false);
          setMessages((prev) => markTurnComplete(prev));
          break;

        case 'cleared':
          setMessages([]);
          setToolCalls([]);
          setFileEdits([]);
          addTerminalLog('[系统] 会话已清空');
          break;

        case 'interrupted':
          setIsRunning(false);
          setMessages((prev) => markTurnComplete(prev));
          addTerminalLog('[系统] 用户中断');
          break;
      }
    },
    [addTerminalLog, attachWorkerEvent, recordFileEdit, takePendingWorkerEvents]
  );

  const { isConnected, send, disconnect } = useWebSocket(sessionId, handleMessage);

  // 加载持久化数据
  useEffect(() => {
    let mounted = true;
    loadSession(sessionId).then((data) => {
      if (!mounted || !data) return;
      setMessages(data.messages || []);
      setToolCalls(data.toolCalls || []);
      setFileEdits(data.fileEdits || []);
    });
    return () => { mounted = false; };
  }, [sessionId]);

  // 自动保存到 IndexedDB（debounce 1s）
  useEffect(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveSession(sessionId, messages, toolCalls, fileEdits).catch(console.error);
    }, 1000);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [sessionId, messages, toolCalls, fileEdits]);

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
        addTerminalLog('[错误] WebSocket 未连接，消息未发送');
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
    setFileEdits([]);
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
    fileEdits,
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
    onFileEditRef,
    recordFileEdit,
    saveInputDraft,
    loadInputDraft,
    clearInputDraft,
  };
}
