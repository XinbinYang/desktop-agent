import { useState, useCallback, useRef, useEffect, useLayoutEffect } from 'react';
import {
  ChatMessage,
  ToolCall,
  AssistantBlock,
  WS_EVENT,
  WorkerEvent,
  FileEdit,
  ToolSummary,
  ClientChatMode,
  errorMessage,
  isRetryableError,
  ThinkingIntensity,
  PlanQuestion,
  PlanState,
  PlanTodo,
  StructuredPlanDraft,
  RunEvent,
  AgentType,
} from '../types';
import { useWebSocket } from './useWebSocket';
import { API_BASE } from '../config';
import { saveSession, loadSession, saveDraft, loadDraft, deleteDraft } from '../lib/db';

function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function initialChatModeFromStorage(): ClientChatMode {
  try {
    const v = localStorage.getItem('desktop-agent-chat-mode');
    return v === 'plan' ? 'plan' : 'agent';
  } catch {
    return 'agent';
  }
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

function toolBucketLabel(name: string): string {
  const n = (name || '').toLowerCase();
  if (n.includes('file_read')) return 'Read';
  if (n.includes('file_search')) return 'Search';
  if (n.includes('file_list')) return 'List';
  if (n.includes('file_write') || n.includes('file_patch') || n.includes('file_edit')) return 'Edit';
  if (n.includes('code_search') || n.includes('repo_map') || n.includes('file_outline')) return 'Code';
  if (n.includes('verify_project') || n.includes('run_review')) return 'Verify';
  if (n.includes('shell')) return 'Shell';
  if (n.includes('browser')) return 'Browser';
  if (n.includes('dispatch') || n.includes('worker')) return 'Agent';
  return n ? n.replace(/_/g, ' ') : 'Tool';
}

function buildToolSummary(blocks?: AssistantBlock[]): ToolSummary | undefined {
  if (!blocks || blocks.length === 0) return undefined;
  const toolBlocks = blocks.filter((b): b is Extract<AssistantBlock, { type: 'tool_call' }> => b.type === 'tool_call');
  if (toolBlocks.length === 0) return undefined;

  const total = toolBlocks.length;
  const success = toolBlocks.filter((b) => b.status === 'success').length;
  const error = toolBlocks.filter((b) => b.status === 'error').length;
  const running = toolBlocks.filter((b) => b.status === 'running').length;

  const buckets = new Map<string, number>();
  for (const block of toolBlocks) {
    const label = toolBucketLabel(block.name);
    buckets.set(label, (buckets.get(label) || 0) + 1);
  }
  const toolBuckets = [...buckets.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([label, count]) => ({ label, count }));

  return { total, success, error, running, toolBuckets };
}

function refreshLatestAssistantSummary(messages: ChatMessage[]): ChatMessage[] {
  if (messages.length === 0) return messages;
  const updated = [...messages];
  for (let i = updated.length - 1; i >= 0; i--) {
    if (updated[i].role !== 'assistant') continue;
    const summary = buildToolSummary(updated[i].blocks);
    updated[i] = { ...updated[i], toolSummary: summary };
    return updated;
  }
  return messages;
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

function contentToText(content: any): string {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => {
        if (typeof part === 'string') return part;
        if (part?.type === 'text') return part.text || '';
        return '';
      })
      .filter(Boolean)
      .join('\n');
  }
  return content == null ? '' : String(content);
}

function parseToolArgs(raw: any): Record<string, any> {
  if (!raw) return {};
  if (typeof raw === 'object') return raw;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function sessionSnapshotToState(snapshot: any): {
  messages: ChatMessage[];
  toolCalls: ToolCall[];
  chatMode?: ClientChatMode;
  thinkingIntensity?: ThinkingIntensity;
  planState?: PlanState;
} {
  const restoredMessages: ChatMessage[] = [];
  const restoredToolCalls: ToolCall[] = [];
  const pendingTools = new Map<string, { messageIndex: number; blockIndex: number; name: string; args: Record<string, any> }>();

  for (const msg of snapshot?.messages || []) {
    const role = msg?.role;
    if (role === 'system') continue;

    if (role === 'user') {
      const text = contentToText(msg.content);
      restoredMessages.push({
        id: generateId(),
        role: 'user',
        content: text,
        isTool: false,
        turnComplete: true,
      });
      continue;
    }

    if (role === 'assistant') {
      const blocks: AssistantBlock[] = [];
      const timestamp = Date.now();
      if (msg.reasoning_content) {
        blocks.push({ type: 'thinking', text: msg.reasoning_content, timestamp });
      }
      const text = contentToText(msg.content);
      if (text) {
        blocks.push({ type: 'text', text, timestamp });
      }
      for (const tc of msg.tool_calls || []) {
        const func = tc.function || {};
        const args = parseToolArgs(func.arguments);
        const block: AssistantBlock = {
          type: 'tool_call',
          name: func.name || '',
          args,
          result: '[executed]',
          status: 'success',
          toolCallId: tc.id,
          timestamp,
        };
        pendingTools.set(tc.id || `${func.name}_${blocks.length}`, {
          messageIndex: restoredMessages.length,
          blockIndex: blocks.length,
          name: func.name || '',
          args,
        });
        blocks.push(block);
      }
      if (blocks.length > 0) {
        restoredMessages.push({
          id: generateId(),
          role: 'assistant',
          content: text,
          isTool: false,
          blocks,
          toolSummary: buildToolSummary(blocks),
          turnComplete: true,
        });
      }
      continue;
    }

    if (role === 'tool') {
      const toolCallId = msg.tool_call_id || '';
      const pending = pendingTools.get(toolCallId);
      const result = contentToText(msg.content);
      if (pending) {
        const target = restoredMessages[pending.messageIndex];
        const blocks = [...(target.blocks || [])];
        const block = blocks[pending.blockIndex];
        if (block?.type === 'tool_call') {
          blocks[pending.blockIndex] = {
            ...block,
            result,
            status: result.startsWith('[ERROR]') ? 'error' : 'success',
          };
          restoredMessages[pending.messageIndex] = {
            ...target,
            blocks,
            toolSummary: buildToolSummary(blocks),
          };
        }
        restoredToolCalls.push({
          name: pending.name || msg.name || '',
          args: pending.args,
          result,
          timestamp: Date.now(),
          toolCallId,
        });
      } else {
        restoredToolCalls.push({
          name: msg.name || '',
          args: {},
          result,
          timestamp: Date.now(),
          toolCallId,
        });
      }
    }
  }

  const chatMode = snapshot?.chat_mode === 'plan' ? 'plan' : snapshot?.chat_mode === 'agent' ? 'agent' : undefined;
  const thinkingIntensity =
    snapshot?.thinking_intensity === 'low' || snapshot?.thinking_intensity === 'medium' || snapshot?.thinking_intensity === 'high'
      ? snapshot.thinking_intensity
      : undefined;

  return {
    messages: restoredMessages,
    toolCalls: restoredToolCalls,
    chatMode,
    thinkingIntensity,
    planState: snapshot?.plan_state,
  };
}

export function useChatSession(
  sessionId: string,
  currentModel: string,
  agentTypeOrRole: AgentType | string = 'personal',
  explicitRoleId?: string,
) {
  const agentType: AgentType =
    agentTypeOrRole === 'coding' || agentTypeOrRole === 'personal'
      ? agentTypeOrRole
      : agentTypeOrRole === 'code-expert'
        ? 'coding'
        : 'personal';
  const roleId = explicitRoleId || (
    agentTypeOrRole === 'coding' || agentTypeOrRole === 'personal'
      ? (agentType === 'coding' ? 'code-expert' : 'desktop-agent')
      : agentTypeOrRole || (agentType === 'coding' ? 'code-expert' : 'desktop-agent')
  );
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [fileEdits, setFileEdits] = useState<FileEdit[]>([]);
  const [runEvents, setRunEvents] = useState<RunEvent[]>([]);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [suggestAgentSwitch, setSuggestAgentSwitch] = useState<{
    from: string; to: string; reason: string;
  } | null>(null);
  const [chatMode, setChatModeState] = useState<ClientChatMode>(() => initialChatModeFromStorage());
  const sendRef = useRef<(obj: object) => boolean>(() => false);
  const chatModeRef = useRef<ClientChatMode>(initialChatModeFromStorage());
  const [thinkingIntensity, setThinkingIntensity] = useState<ThinkingIntensity>(() => {
    try {
      const v = localStorage.getItem('desktop-agent-thinking-intensity');
      if (v === 'low' || v === 'medium' || v === 'high') return v;
    } catch { /* ignore */ }
    return 'medium';
  });
  const [planState, setPlanState] = useState<PlanState>({
    mode: 'agent',
    phase: 'idle',
    goal: '',
    draft: '',
    structured_plan: null,
    questions: [],
    todos: [],
    decisions: {},
    approved: false,
    pending_clarification: false,
    plan_file_path: null,
    research_notes: '',
  });

  const onToolCallRef = useRef<((tc: ToolCall) => void) | null>(null);
  const onFileEditRef = useRef<((edit: FileEdit) => void) | null>(null);
  const pendingWorkerEventsRef = useRef<Record<string, WorkerEvent[]>>({});
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const userTouchedRef = useRef(false);
  const [hydratedSessionId, setHydratedSessionId] = useState('');

  const addTerminalLog = useCallback((log: string) => {
    setTerminalLogs((prev) => [
      ...prev.slice(-200),
      `[${new Date().toLocaleTimeString()}] ${log}`,
    ]);
  }, []);

  const recordRunEvent = useCallback((event: WS_EVENT) => {
    const runEvent: RunEvent = {
      id: `${event.type}_${event.data?.run_id || 'run'}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      type: event.type as RunEvent['type'],
      runId: event.data?.run_id,
      timestamp: event.data?.timestamp ? event.data.timestamp * 1000 : Date.now(),
      data: event.data || {},
    };
    setRunEvents((prev) => [...prev.slice(-300), runEvent]);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem('desktop-agent-chat-mode', chatMode);
    } catch { /* ignore */ }
  }, [chatMode]);

  useEffect(() => {
    chatModeRef.current = chatMode;
  }, [chatMode]);

  useEffect(() => {
    try {
      localStorage.setItem('desktop-agent-thinking-intensity', thinkingIntensity);
    } catch { /* ignore */ }
  }, [thinkingIntensity]);

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
        case 'history_snapshot': {
          const restored = sessionSnapshotToState(event.data);
          setMessages(restored.messages);
          setToolCalls(restored.toolCalls);
          setFileEdits([]);
          const fromServer = restored.chatMode;
          const serverPlanPhase = (event.data as { plan_state?: { phase?: string } })?.plan_state?.phase;
          const prev = chatModeRef.current;
          let merged: ClientChatMode = prev;
          if (!fromServer) {
            merged = prev;
          } else if (fromServer === 'plan') {
            merged = 'plan';
          } else if (prev === 'plan' && fromServer === 'agent') {
            merged = serverPlanPhase && serverPlanPhase !== 'idle' ? 'plan' : prev;
          } else {
            merged = fromServer;
          }
          setChatModeState(merged);
          if (merged === 'plan' && fromServer === 'agent') {
            sendRef.current({ type: 'set_chat_mode', chat_mode: 'plan' });
          }
          if (restored.thinkingIntensity) setThinkingIntensity(restored.thinkingIntensity);
          if (restored.planState) setPlanState((prev) => ({ ...prev, ...restored.planState }));
          setHydratedSessionId(sessionId);
          break;
        }

        case 'chat_mode': {
          const m = event.data?.chat_mode;
          if (m === 'plan' || m === 'agent') {
            setChatModeState(m);
          }
          break;
        }

        case 'content':
          userTouchedRef.current = true;
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
            if (withUpdate) return refreshLatestAssistantSummary(withUpdate);
            return refreshLatestAssistantSummary(appendBlock(
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
            ));
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
            refreshLatestAssistantSummary(appendBlock(
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
            )),
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

        case 'run_created':
          recordRunEvent(event);
          addTerminalLog(`[Run] ${event.data.run_id || ''} ${event.data.mode || ''} ${event.data.worktree_path || event.data.project_path || ''}`.trim());
          break;

        case 'context_pack':
          recordRunEvent(event);
          addTerminalLog(`[Run] Context pack ready (${(event.data.files || []).length} files shown)`);
          break;

        case 'guardrail_decision':
        case 'approval_required':
          recordRunEvent(event);
          addTerminalLog(`[Guardrail] ${event.data.decision || 'decision'}: ${event.data.reason || ''}`);
          break;

        case 'verification_start':
          recordRunEvent(event);
          addTerminalLog(`[Verify] ${event.data.command || ''}`);
          break;

        case 'verification_result':
          recordRunEvent(event);
          addTerminalLog(`[Verify] ${event.data.passed ? 'passed' : 'failed'}: ${event.data.command || ''}`);
          break;

        case 'review_finding':
          recordRunEvent(event);
          addTerminalLog(`[Review] ${event.data.severity || 'info'}: ${event.data.message || ''}`);
          break;

        case 'run_completed':
          recordRunEvent(event);
          addTerminalLog(`[Run] ${event.data.status || 'completed'}: ${event.data.summary || ''}`);
          break;

        case 'status': {
          const status = event.data.status;
          if (status === 'executing') {
            // Push a running placeholder — the matching tool_call event will fill in details
            setMessages((prev) =>
              refreshLatestAssistantSummary(appendBlock(
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
              )),
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

        case 'plan_status':
          setPlanState((prev) => ({
            ...prev,
            mode: (event.data.mode || prev.mode) as ClientChatMode,
            phase: event.data.phase || prev.phase,
            approved: typeof event.data.approved === 'boolean' ? event.data.approved : prev.approved,
            goal: event.data.goal || prev.goal,
            structured_plan: event.data.structured_plan ?? prev.structured_plan,
            pending_clarification:
              typeof event.data.pending_clarification === 'boolean'
                ? event.data.pending_clarification
                : prev.pending_clarification,
            plan_file_path:
              event.data.plan_file_path !== undefined ? event.data.plan_file_path : prev.plan_file_path,
            research_notes:
              typeof event.data.research_notes === 'string' ? event.data.research_notes : prev.research_notes,
          }));
          break;

        case 'plan_draft': {
          const draftTodos = Array.isArray(event.data.todos) ? event.data.todos as PlanTodo[] : [];
          const draftStructured = (event.data.structured_plan ?? null) as StructuredPlanDraft | null;
          setPlanState((prev) => ({
            ...prev,
            mode: 'plan',
            draft: event.data.draft || '',
            todos: draftTodos.length > 0 ? draftTodos : prev.todos,
            phase: event.data.phase || prev.phase,
            goal: event.data.goal || prev.goal,
            structured_plan: draftStructured ?? prev.structured_plan,
            pending_clarification:
              typeof event.data.pending_clarification === 'boolean'
                ? event.data.pending_clarification
                : prev.pending_clarification,
          }));
          // Inject plan draft card into the chat stream
          setMessages((prev) => appendBlock(prev, {
            type: 'plan_draft',
            goal: event.data.goal || '',
            draft: event.data.draft || '',
            todos: draftTodos,
            structured_plan: draftStructured,
            timestamp: Date.now(),
          }, false));
          break;
        }

        case 'plan_questions': {
          const questions = Array.isArray(event.data.questions) ? event.data.questions as PlanQuestion[] : [];
          setPlanState((prev) => ({
            ...prev,
            mode: 'plan',
            questions,
            phase: event.data.phase || 'awaiting_decision',
            pending_clarification:
              typeof event.data.pending_clarification === 'boolean'
                ? event.data.pending_clarification
                : prev.pending_clarification,
          }));
          // Inject interactive question card into the chat stream
          setMessages((prev) => appendBlock(prev, {
            type: 'plan_questions',
            questions,
            timestamp: Date.now(),
          }, false));
          break;
        }

        case 'plan_approved_waiting_build':
          setPlanState((prev) => ({
            ...prev,
            approved: true,
            phase: 'approved_waiting_build',
          }));
          addTerminalLog('[计划] 已批准，等待 Build 启动');
          setIsRunning(false);
          break;

        case 'build_started':
          setPlanState((prev) => ({
            ...prev,
            phase: 'executing',
          }));
          addTerminalLog('[计划] Build 已启动，进入执行阶段');
          break;

        case 'plan_rejected':
          setPlanState((prev) => ({
            ...prev,
            approved: false,
            phase: 'clarifying',
            pending_clarification: false,
          }));
          addTerminalLog('[计划] 已拒绝，等待修订');
          break;

        case 'todo_update':
          setPlanState((prev) => ({
            ...prev,
            todos: Array.isArray(event.data.todos) ? event.data.todos as PlanTodo[] : prev.todos,
          }));
          break;

        case 'plan_file_ready':
          setPlanState((prev) => ({
            ...prev,
            plan_file_path: typeof event.data.plan_file_path === 'string' ? event.data.plan_file_path : prev.plan_file_path,
            draft: typeof event.data.markdown === 'string' ? event.data.markdown : prev.draft,
          }));
          addTerminalLog(`[计划] 文件已保存: ${event.data.plan_file_path}`);
          break;

        case 'error': {
          const msg = errorMessage(event.data);
          const retryable = isRetryableError(event.data);
          setMessages((prev) => {
            const complete = markTurnComplete(prev);
            return [
              ...complete,
              {
                id: generateId(),
                role: 'system',
                content: retryable ? `⚠️ ${msg} (可重试)` : `错误: ${msg}`,
                isTool: false,
              },
            ];
          });
          if (!retryable) {
            setIsRunning(false);
          }
          addTerminalLog(`[错误${retryable ? '·可重试' : ''}] ${msg}`);
          break;
        }

        case 'compacted':
          addTerminalLog(`[压缩] 对话已压缩，从 ${event.data.message_count || '?'} 条消息中提取摘要`);
          break;

        case 'model_switched':
          addTerminalLog(`[模型] 已切换至 ${event.data.model_id}`);
          break;

        case 'done':
          setIsRunning(false);
          setMessages((prev) => markTurnComplete(prev));
          break;

        case 'cleared':
          setMessages([]);
          setToolCalls([]);
          setFileEdits([]);
          setRunEvents([]);
          setChatModeState('agent');
          setPlanState({
            mode: 'agent',
            phase: 'idle',
            goal: '',
            draft: '',
            structured_plan: null,
            questions: [],
            todos: [],
            decisions: {},
            approved: false,
            pending_clarification: false,
          });
          addTerminalLog('[系统] 会话已清空');
          break;

        case 'interrupted':
          setIsRunning(false);
          setMessages((prev) => markTurnComplete(prev));
          addTerminalLog('[系统] 用户中断');
          break;

        case 'suggest_agent_switch':
          setSuggestAgentSwitch({
            from: event.data?.from || 'personal',
            to: event.data?.to || 'coding',
            reason: event.data?.reason || '',
          });
          break;
      }
    },
    [addTerminalLog, attachWorkerEvent, recordFileEdit, recordRunEvent, sessionId, takePendingWorkerEvents]
  );

  const { isConnected, send, disconnect } = useWebSocket(sessionId, handleMessage);

  useLayoutEffect(() => {
    sendRef.current = send;
  }, [send]);

  const setChatMode = useCallback((mode: ClientChatMode) => {
    setChatModeState(mode);
    sendRef.current({ type: 'set_chat_mode', chat_mode: mode });
  }, []);

  useEffect(() => {
    if (!isConnected) return;
    send({ type: 'set_chat_mode', chat_mode: chatModeRef.current });
  }, [isConnected, sessionId, send]);

  // 加载持久化数据（不强制 WS：连接后的 effect 会同步 chat_mode）
  useEffect(() => {
    let mounted = true;
    userTouchedRef.current = false;
    setHydratedSessionId('');

    const hydrate = async () => {
      const data = await loadSession(sessionId);
      if (!mounted || userTouchedRef.current) return;
      if (data && ((data.messages || []).length > 0 || (data.toolCalls || []).length > 0)) {
        setMessages(data.messages || []);
        setToolCalls(data.toolCalls || []);
        setFileEdits(data.fileEdits || []);
        if (data.chatMode === 'plan' || data.chatMode === 'agent') {
          setChatModeState(data.chatMode);
        }
        if (data.thinkingIntensity === 'low' || data.thinkingIntensity === 'medium' || data.thinkingIntensity === 'high') {
          setThinkingIntensity(data.thinkingIntensity);
        }
        if (data.planState) {
          setPlanState((prev) => ({ ...prev, ...data.planState }));
        }
        setHydratedSessionId(sessionId);
        return;
      }

      try {
        const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`);
        const snapshot = await res.json();
        if (!mounted || userTouchedRef.current || snapshot?.error) return;
        const restored = sessionSnapshotToState(snapshot);
        setMessages(restored.messages);
        setToolCalls(restored.toolCalls);
        setFileEdits([]);
        if (restored.chatMode) setChatModeState(restored.chatMode);
        if (restored.thinkingIntensity) setThinkingIntensity(restored.thinkingIntensity);
        if (restored.planState) setPlanState((prev) => ({ ...prev, ...restored.planState }));
      } catch {
        // The WebSocket history snapshot can still hydrate the session.
      } finally {
        if (mounted) setHydratedSessionId(sessionId);
      }
    };

    hydrate();
    return () => { mounted = false; };
  }, [sessionId]);

  // 自动保存到 IndexedDB（debounce 1s）
  useEffect(() => {
    let cancelled = false;
    const loadRunJournal = async () => {
      try {
        const listRes = await fetch(`${API_BASE}/api/runs?limit=20`);
        const listData = await listRes.json();
        const runIds = (listData.runs || [])
          .filter((run: any) => !run.session_id || run.session_id === sessionId)
          .slice(0, 6)
          .map((run: any) => run.run_id)
          .filter(Boolean);
        const details = await Promise.all(
          runIds.map(async (runId: string) => {
            const res = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}`);
            return res.json();
          }),
        );
        if (cancelled) return;
        const restored: RunEvent[] = [];
        for (const detail of details) {
          const runId = detail?.run?.run_id;
          for (const event of detail?.events || []) {
            const data = event.data || {};
            restored.push({
              id: `${event.type}_${runId || data.run_id || 'run'}_${event.timestamp}`,
              type: event.type as RunEvent['type'],
              runId: data.run_id || runId,
              timestamp: event.timestamp ? event.timestamp * 1000 : Date.now(),
              data,
            });
          }
        }
        setRunEvents((prev) => (prev.length > 0 ? prev : restored));
      } catch {
        // History restore is best-effort; live WebSocket events remain authoritative for the current turn.
      }
    };
    loadRunJournal();
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => {
    if (hydratedSessionId !== sessionId) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveSession(sessionId, messages, toolCalls, fileEdits, {
        chatMode,
        thinkingIntensity,
        planState,
      }).catch(console.error);
    }, 1000);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [sessionId, hydratedSessionId, messages, toolCalls, fileEdits, chatMode, thinkingIntensity, planState]);

  const sendMessage = useCallback(
    (text: string, imageBase64?: string, overrides?: { chatMode?: ClientChatMode; thinkingIntensity?: ThinkingIntensity }) => {
      if (!text.trim() && !imageBase64) return;
      if (!currentModel) {
        addTerminalLog('[错误] 模型未加载，请等待页面加载完成');
        return;
      }
      userTouchedRef.current = true;
      setHydratedSessionId(sessionId);
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
        agent_type: agentType,
        role_id: roleId,
        image_base64: imageBase64,
        chat_mode: overrides?.chatMode || chatMode,
        thinking_intensity: overrides?.thinkingIntensity || thinkingIntensity,
      });
      if (sent === false) {
        setIsRunning(false);
        addTerminalLog('[错误] WebSocket 未连接，消息未发送');
      }
    },
    [send, sessionId, currentModel, agentType, roleId, addTerminalLog, chatMode, thinkingIntensity]
  );

  const clearSession = useCallback(() => {
    send({ type: 'clear' });
  }, [send]);

  const stopRunning = useCallback(() => {
    send({ type: 'stop' });
  }, [send]);

  const retryLast = useCallback(() => {
    send({
      type: 'retry',
      model_id: currentModel,
      agent_type: agentType,
      role_id: roleId,
      chat_mode: chatMode,
      thinking_intensity: thinkingIntensity,
    });
    setIsRunning(true);
  }, [send, currentModel, agentType, roleId, chatMode, thinkingIntensity]);

  const approvePlan = useCallback(() => {
    setIsRunning(false);
    send({ type: 'approve_plan' });
  }, [send]);

  const buildPlan = useCallback(() => {
    setIsRunning(true);
    send({ type: 'build_plan' });
  }, [send]);

  const rejectPlan = useCallback(() => {
    send({ type: 'reject_plan' });
  }, [send]);

  const updatePlanDecision = useCallback((questionId: string, selected: string[]) => {
    send({ type: 'update_plan_decision', question_id: questionId, selected });
    setPlanState((prev) => ({
      ...prev,
      decisions: { ...prev.decisions, [questionId]: selected },
      questions: prev.questions.map((q) => (q.id === questionId ? { ...q, selected } : q)),
    }));
  }, [send]);

  const executeToolDirect = useCallback(
    (toolName: string, args: any) => {
      send({ type: 'tool_direct', tool_name: toolName, args });
    },
    [send]
  );

  const resetSession = useCallback(() => {
    disconnect();
    userTouchedRef.current = false;
    setHydratedSessionId('');
    setMessages([]);
    setToolCalls([]);
    setFileEdits([]);
    setRunEvents([]);
    setTerminalLogs([]);
    setIsRunning(false);
    setChatModeState(initialChatModeFromStorage());
    setPlanState({
      mode: 'agent',
      phase: 'idle',
      goal: '',
      draft: '',
      structured_plan: null,
      questions: [],
      todos: [],
      decisions: {},
      approved: false,
      pending_clarification: false,
    });
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

  const clearSuggestAgentSwitch = useCallback(() => setSuggestAgentSwitch(null), []);

  return {
    messages,
    toolCalls,
    fileEdits,
    runEvents,
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
    sendRaw: send,
    saveInputDraft,
    loadInputDraft,
    clearInputDraft,
    chatMode,
    setChatMode,
    thinkingIntensity,
    setThinkingIntensity,
    planState,
    approvePlan,
    buildPlan,
    rejectPlan,
    updatePlanDecision,
    suggestAgentSwitch,
    clearSuggestAgentSwitch,
  };
}
