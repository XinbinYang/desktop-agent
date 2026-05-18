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
  PlanDecisionAnswer,
  PlanState,
  PlanTodo,
  StructuredPlanDraft,
  RunEvent,
  AgentType,
  ContextUsage,
  ConversationCheckpoint,
  TaskGuidanceItem,
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

function isThinkingIntensity(value: unknown): value is ThinkingIntensity {
  return value === 'low' || value === 'medium' || value === 'high';
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
      // Never resurrect a sealed thinking block: a `reasoning` event arriving
      // after a tool/answer must start a NEW thinking block (its own timer).
      const sealedThinking =
        lastBlock.type === 'thinking' && (lastBlock as { complete?: boolean }).complete === true;
      if (
        lastBlock.type === block.type &&
        (lastBlock.type === 'thinking' || lastBlock.type === 'text') &&
        !sealedThinking
      ) {
        // The first real token replaces the "Waiting for model response..."
        // placeholder instead of being appended after it.
        const prevText = (lastBlock as { text: string }).text;
        const base = prevText === THINKING_PLACEHOLDER_TEXT ? '' : prevText;
        blocks[blocks.length - 1] = {
          ...lastBlock,
          text: base + (block as { text: string }).text,
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

function hasOnlyPlanQuestionNoise(blocks: AssistantBlock[] = []): boolean {
  return blocks.every((block) =>
    block.type === 'thinking' ||
    block.type === 'text' ||
    (block.type === 'tool_call' && block.name === 'plan_ask_questions')
  );
}

function dropOpenPlanQuestionNoise(messages: ChatMessage[]): ChatMessage[] {
  if (messages.length === 0) return messages;
  const updated = [...messages];
  const last = updated[updated.length - 1];
  if (!last || last.role !== 'assistant' || last.turnComplete || !last.blocks) return messages;
  if (!hasOnlyPlanQuestionNoise(last.blocks)) return messages;
  return updated.slice(0, -1);
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

const THINKING_PLACEHOLDER_TEXT = 'Waiting for model response...';

function stripThinkingPlaceholder(text: string): string {
  return text.startsWith(THINKING_PLACEHOLDER_TEXT)
    ? text.slice(THINKING_PLACEHOLDER_TEXT.length).replace(/^\s+/, '')
    : text;
}

function sanitizeThinkingPlaceholders(messages: ChatMessage[]): ChatMessage[] {
  let changed = false;
  const sanitized = messages.map((message) => {
    if (message.role !== 'assistant' || !message.blocks) return message;

    const blocks = message.blocks
      .map((block) => {
        if (block.type !== 'thinking') return block;
        const nextText = stripThinkingPlaceholder(block.text || '');
        if (nextText === block.text) return block;
        changed = true;
        return { ...block, text: nextText };
      })
      .filter((block) => block.type !== 'thinking' || (block.text || '').trim().length > 0);

    if (blocks.length !== message.blocks.length) changed = true;
    return changed ? { ...message, blocks } : message;
  });
  return changed ? sanitized : messages;
}

/**
 * Seal the most recent still-open thinking block (frontend-derived
 * completion). Called before appending any non-thinking block and on every
 * turn-ending event, so the live thinking window auto-collapses into a
 * "Thought for Ns" summary and its timer freezes.
 */
function completeOpenThinking(messages: ChatMessage[]): ChatMessage[] {
  const result = mergeBlock(
    messages,
    (b) => b.type === 'thinking' && !(b as { complete?: boolean }).complete,
    (b) => ({ ...b, complete: true, endedAt: Date.now() } as AssistantBlock),
  );
  return result ?? messages;
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

function imageUrlToBase64(value: any): string | undefined {
  const url =
    typeof value === 'string'
      ? value
      : typeof value?.url === 'string'
        ? value.url
        : typeof value?.image_url?.url === 'string'
          ? value.image_url.url
          : '';
  const match = url.match(/^data:image\/[^;]+;base64,(.+)$/);
  return match?.[1];
}

function extractBase64Image(content: any): string | undefined {
  if (!Array.isArray(content)) return undefined;
  for (const part of content) {
    if (!part || typeof part !== 'object') continue;
    const type = part.type;
    if (type === 'image_url') {
      const encoded = imageUrlToBase64(part.image_url || part);
      if (encoded) return encoded;
    }
    if (type === 'image' && part.source?.type === 'base64' && typeof part.source.data === 'string') {
      return part.source.data;
    }
  }
  return undefined;
}

function countAttachments(content: any): number {
  if (!Array.isArray(content)) return 0;
  return content.filter((part) => {
    if (!part || typeof part !== 'object') return false;
    return part.type === 'image_url' || part.type === 'image';
  }).length;
}

function partToText(part: any): string {
  if (typeof part === 'string') return part;
  if (!part || typeof part !== 'object') return '';
  if (part.type === 'image_url' || part.type === 'image') return '';
  const value =
    part.text ??
    part.input_text ??
    part.output_text ??
    part.content ??
    part.value ??
    '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return contentToText(value);
  return value == null ? '' : String(value);
}

function contentToText(content: any): string {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    const text = content
      .map(partToText)
      .filter(Boolean)
      .join('\n');
    return text || (countAttachments(content) > 0 ? '[image]' : '');
  }
  if (content && typeof content === 'object') {
    const direct = partToText(content);
    if (direct) return direct;
    try {
      return JSON.stringify(content);
    } catch {
      return String(content);
    }
  }
  return content == null ? '' : String(content);
}

function isRenderableMessage(message: ChatMessage): boolean {
  if (message.role !== 'user') return true;
  return !!(
    (message.content && message.content.trim()) ||
    message.imageBase64 ||
    (message.attachmentCount || 0) > 0
  );
}

function sanitizeCachedMessages(messages: any[]): ChatMessage[] {
  if (!Array.isArray(messages)) return [];
  return (messages as ChatMessage[]).filter(isRenderableMessage);
}

function mergeSnapshotWithOptimistic(current: ChatMessage[], restored: ChatMessage[]): ChatMessage[] {
  const equivalentUser = (candidate: ChatMessage) =>
    restored.some((msg) =>
      msg.role === 'user' &&
      msg.content === candidate.content &&
      (msg.imageBase64 || '') === (candidate.imageBase64 || '')
    );

  const pending = current.filter((msg) =>
    msg.role === 'user' &&
    !msg.messageId &&
    !msg.turnId &&
    isRenderableMessage(msg) &&
    !equivalentUser(msg)
  );
  return pending.length > 0 ? [...restored, ...pending] : restored;
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

function mergeTaskGuidanceItems(
  current: TaskGuidanceItem[],
  incoming: TaskGuidanceItem[],
): TaskGuidanceItem[] {
  const byId = new Map<string, TaskGuidanceItem>();
  for (const item of current) {
    if (item?.id && item.status !== 'consumed') byId.set(item.id, item);
  }
  for (const item of incoming) {
    if (!item?.id) continue;
    if (item.status === 'consumed') {
      byId.delete(item.id);
    } else {
      byId.set(item.id, item);
    }
  }
  return Array.from(byId.values()).sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
}

function sessionSnapshotToState(snapshot: any): {
  messages: ChatMessage[];
  toolCalls: ToolCall[];
  chatMode?: ClientChatMode;
  thinkingIntensity?: ThinkingIntensity;
  planState?: PlanState;
  contextUsage?: ContextUsage | null;
  checkpoints?: ConversationCheckpoint[];
  taskGuidanceItems?: TaskGuidanceItem[];
} {
  const restoredMessages: ChatMessage[] = [];
  const restoredToolCalls: ToolCall[] = [];
  const pendingTools = new Map<string, { messageIndex: number; blockIndex: number; name: string; args: Record<string, any> }>();

  for (const msg of snapshot?.messages || []) {
    const role = msg?.role;
    if (role === 'system') continue;

    if (role === 'user') {
      // Internal synthetic prompts are LLM-only — never render them as
      // user chat bubbles (defense-in-depth; backend to_snapshot also filters).
      if (msg?.source === 'internal') continue;
      const text = contentToText(msg.content);
      const imageBase64 = extractBase64Image(msg.content);
      const attachmentCount = countAttachments(msg.content);
      if (!text.trim() && !imageBase64 && attachmentCount === 0) continue;
      restoredMessages.push({
        id: msg.message_id || generateId(),
        role: 'user',
        content: text,
        rawContent: msg.content,
        imageBase64,
        attachmentCount,
        messageId: msg.message_id,
        turnId: msg.turn_id,
        checkpointId: msg.checkpoint_id,
        createdAt: typeof msg.created_at === 'number' ? msg.created_at * 1000 : undefined,
        isTool: false,
        turnComplete: true,
      });
      continue;
    }

    if (role === 'assistant') {
      const blocks: AssistantBlock[] = [];
      const timestamp = Date.now();
      if (msg.reasoning_content) {
        // Restored from history: already finished. No startedAt → the block
        // renders collapsed with a plain "Thought" label (no live timer).
        blocks.push({ type: 'thinking', text: msg.reasoning_content, timestamp, complete: true });
      }
      const text = contentToText(msg.content);
      if (text) {
        blocks.push({ type: 'text', text, timestamp });
      }
      for (const tc of msg.tool_calls || []) {
        const func = tc.function || {};
        if (func.name === 'plan_ask_questions') {
          continue;
        }
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
          id: msg.message_id || generateId(),
          role: 'assistant',
          content: text,
          messageId: msg.message_id,
          turnId: msg.turn_id,
          checkpointId: msg.checkpoint_id,
          createdAt: typeof msg.created_at === 'number' ? msg.created_at * 1000 : undefined,
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
    isThinkingIntensity(snapshot?.thinking_intensity)
      ? snapshot.thinking_intensity
      : undefined;

  return {
    messages: sanitizeThinkingPlaceholders(restoredMessages),
    toolCalls: restoredToolCalls,
    chatMode,
    thinkingIntensity,
    planState: snapshot?.plan_state,
    contextUsage: snapshot?.context_usage || null,
    checkpoints: Array.isArray(snapshot?.checkpoints) ? snapshot.checkpoints : [],
    taskGuidanceItems: Array.isArray(snapshot?.task_guidance_items)
      ? snapshot.task_guidance_items.filter((item: any) => item?.id && item?.status !== 'consumed') as TaskGuidanceItem[]
      : [],
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
  const [contextUsage, setContextUsage] = useState<ContextUsage | null>(null);
  const [checkpoints, setCheckpoints] = useState<ConversationCheckpoint[]>([]);
  const [taskGuidanceItems, setTaskGuidanceItems] = useState<TaskGuidanceItem[]>([]);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const isRunningRef = useRef(false);
  const [suggestAgentSwitch, setSuggestAgentSwitch] = useState<{
    from: string; to: string; reason: string;
  } | null>(null);
  const [chatMode, setChatModeState] = useState<ClientChatMode>(() => initialChatModeFromStorage());
  const sendRef = useRef<(obj: object) => boolean>(() => false);
  const chatModeRef = useRef<ClientChatMode>(initialChatModeFromStorage());
  const [thinkingIntensity, setThinkingIntensityState] = useState<ThinkingIntensity>(() => {
    try {
      const v = localStorage.getItem('desktop-agent-thinking-intensity');
      if (isThinkingIntensity(v)) return v;
    } catch { /* ignore */ }
    return 'medium';
  });
  const thinkingIntensityRef = useRef<ThinkingIntensity>(thinkingIntensity);
  const [planState, setPlanState] = useState<PlanState>({
    mode: 'agent',
    phase: 'idle',
    goal: '',
    draft: '',
    structured_plan: null,
    questions: [],
    todos: [],
    decisions: {},
    decision_notes: {},
    approved: false,
    pending_clarification: false,
    plan_file_path: null,
    research_notes: '',
  });
  const planStateRef = useRef<PlanState>(planState);

  const onToolCallRef = useRef<((tc: ToolCall) => void) | null>(null);
  const onFileEditRef = useRef<((edit: FileEdit) => void) | null>(null);
  const pendingWorkerEventsRef = useRef<Record<string, WorkerEvent[]>>({});
  const planBufferedContentRef = useRef('');
  const buildRequestInFlightRef = useRef(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const userTouchedRef = useRef(false);
  const [hydratedSessionId, setHydratedSessionId] = useState('');

  const addTerminalLog = useCallback((log: string) => {
    setTerminalLogs((prev) => [
      ...prev.slice(-200),
      `[${new Date().toLocaleTimeString()}] ${log}`,
    ]);
  }, []);

  const shouldBufferPlanContent = useCallback(() => {
    const plan = planStateRef.current;
    return (
      chatModeRef.current === 'plan' &&
      !plan.approved &&
      (plan.phase === 'clarifying' || plan.phase === 'planning' || plan.phase === 'awaiting_decision')
    );
  }, []);

  const flushPlanBufferedContent = useCallback(() => {
    const text = planBufferedContentRef.current;
    if (!text) return;
    planBufferedContentRef.current = '';
    setMessages((prev) => appendBlock(
      completeOpenThinking(prev),
      { type: 'text', text, timestamp: Date.now() },
      true,
    ));
  }, []);

  const discardPlanBufferedContent = useCallback(() => {
    planBufferedContentRef.current = '';
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
    thinkingIntensityRef.current = thinkingIntensity;
    try {
      localStorage.setItem('desktop-agent-thinking-intensity', thinkingIntensity);
    } catch { /* ignore */ }
  }, [thinkingIntensity]);

  useEffect(() => {
    planStateRef.current = planState;
  }, [planState]);

  useEffect(() => {
    isRunningRef.current = isRunning;
  }, [isRunning]);

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
          setMessages((prev) => mergeSnapshotWithOptimistic(prev, restored.messages));
          setToolCalls(restored.toolCalls);
          setFileEdits([]);
          setContextUsage(restored.contextUsage || null);
          setCheckpoints(restored.checkpoints || []);
          setTaskGuidanceItems(restored.taskGuidanceItems || []);
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
          if (restored.thinkingIntensity) setThinkingIntensityState(restored.thinkingIntensity);
          if (restored.planState) setPlanState((prev) => ({ ...prev, ...restored.planState }));
          setHydratedSessionId(sessionId);
          break;
        }

        case 'chat_mode': {
          const m = event.data?.chat_mode;
          if (m === 'plan' || m === 'agent') {
            chatModeRef.current = m;
            setChatModeState(m);
          }
          break;
        }

        case 'thinking_intensity': {
          const intensity = event.data?.thinking_intensity;
          if (isThinkingIntensity(intensity)) {
            setThinkingIntensityState(intensity);
          }
          break;
        }

        case 'content':
          userTouchedRef.current = true;
          if (shouldBufferPlanContent()) {
            planBufferedContentRef.current += event.data.text || '';
            break;
          }
          setMessages((prev) => {
            // Answer text starting seals any open thinking block.
            const updated = appendBlock(
              completeOpenThinking(prev),
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
              {
                type: 'thinking',
                text: event.data.text,
                timestamp: Date.now(),
                startedAt: Date.now(),
              },
              true,
            ),
          );
          break;

        case 'knowledge_context': {
          const sources = Array.isArray(event.data?.sources) ? event.data.sources : [];
          if (sources.length > 0) {
            setMessages((prev) =>
              appendBlock(
                prev,
                { type: 'knowledge_context', sources, timestamp: Date.now() },
                false,
              ),
            );
            addTerminalLog(`[Knowledge] Using ${sources.length} indexed source${sources.length === 1 ? '' : 's'}`);
          }
          break;
        }

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

          if (event.data.name === 'plan_ask_questions') {
            setMessages((prev) => dropOpenPlanQuestionNoise(completeOpenThinking(prev)));
            break;
          }

          setMessages((prev0) => {
            // A tool landing seals any open thinking block (covers the case
            // where no status:executing event preceded this result).
            const prev = completeOpenThinking(prev0);
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
              completeOpenThinking(prev),
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

        case 'skills_matched':
          recordRunEvent(event);
          addTerminalLog(`[Skills] ${(event.data.skills || []).length} matched, ${(event.data.disabled_matches || []).length} disabled`);
          break;

        case 'skill_draft_ready':
          recordRunEvent(event);
          addTerminalLog(`[Skills] Draft ready: ${event.data.name || event.data.draft_id || ''}`.trim());
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

        case 'collaboration_run_created':
        case 'collaboration_task_update':
        case 'agent_message':
        case 'artifact_ready':
        case 'decision_required':
        case 'collaboration_run_completed': {
          recordRunEvent(event);
          const collabId = event.data?.collaboration_run_id || event.data?.run_id || '';
          if (event.type === 'collaboration_run_created') {
            addTerminalLog(`[Collab] Coding Agent run created ${collabId}`.trim());
          } else if (event.type === 'collaboration_task_update') {
            addTerminalLog(`[Collab] Task ${event.data?.task_id || ''} ${event.data?.status || ''}`.trim());
          } else if (event.type === 'agent_message') {
            addTerminalLog(`[Collab] ${event.data?.agent_type || 'agent'}: ${(event.data?.text || '').slice(0, 160)}`);
          } else if (event.type === 'artifact_ready') {
            addTerminalLog(`[Collab] Artifact ready ${event.data?.artifact?.title || collabId}`.trim());
          } else if (event.type === 'decision_required') {
            addTerminalLog(`[Collab] Decision required ${event.data?.reason || collabId}`.trim());
          } else {
            addTerminalLog(`[Collab] Run ${event.data?.status || 'completed'} ${collabId}`.trim());
          }
          break;
        }

        case 'run_completed':
          recordRunEvent(event);
          addTerminalLog(`[Run] ${event.data.status || 'completed'}: ${event.data.summary || ''}`);
          break;

        case 'status': {
          const status = event.data.status;
          if (status === 'thinking' || status === 'executing' || status === 'running') {
            isRunningRef.current = true;
            setIsRunning(true);
          }
          if (status === 'executing') {
            if (event.data.tool === 'plan_ask_questions') {
              break;
            }
            // Tool execution starting seals the preceding thinking block.
            // Push a running placeholder — the matching tool_call event will fill in details
            setMessages((prev) =>
              refreshLatestAssistantSummary(appendBlock(
                completeOpenThinking(prev),
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
            isRunningRef.current = false;
            setIsRunning(false);
            flushPlanBufferedContent();
            setMessages((prev) => markTurnComplete(completeOpenThinking(prev)));
          }
          addTerminalLog(
            `[状态] ${event.data.status} (迭代: ${event.data.iteration})`
          );
          break;
        }

        case 'plan_status':
          if (event.data.mode === 'agent') {
            chatModeRef.current = event.data.mode;
            setChatModeState(event.data.mode);
          } else if (
            event.data.mode === 'plan' &&
            event.data.phase !== 'executing' &&
            event.data.phase !== 'completed'
          ) {
            chatModeRef.current = 'plan';
            setChatModeState('plan');
          }
          setPlanState((prev) => ({
            ...prev,
            mode: (event.data.mode || prev.mode) as ClientChatMode,
            phase: event.data.phase || prev.phase,
            approved: typeof event.data.approved === 'boolean' ? event.data.approved : prev.approved,
            goal: typeof event.data.goal === 'string' ? event.data.goal : prev.goal,
            draft: typeof event.data.draft === 'string' ? event.data.draft : prev.draft,
            structured_plan:
              event.data.structured_plan !== undefined ? event.data.structured_plan : prev.structured_plan,
            questions: Array.isArray(event.data.questions) ? event.data.questions as PlanQuestion[] : prev.questions,
            todos: Array.isArray(event.data.todos) ? event.data.todos as PlanTodo[] : prev.todos,
            decisions:
              event.data.decisions && typeof event.data.decisions === 'object'
                ? event.data.decisions as Record<string, string[]>
                : prev.decisions,
            decision_notes:
              event.data.decision_notes && typeof event.data.decision_notes === 'object'
                ? event.data.decision_notes as Record<string, string>
                : prev.decision_notes,
            pending_clarification:
              typeof event.data.pending_clarification === 'boolean'
                ? event.data.pending_clarification
                : prev.pending_clarification,
            plan_file_path:
              event.data.plan_file_path !== undefined ? event.data.plan_file_path : prev.plan_file_path,
            research_notes:
              typeof event.data.research_notes === 'string' ? event.data.research_notes : prev.research_notes,
          }));
          if (event.data.phase === 'planning') {
            setIsRunning(true);
          }
          break;

        case 'plan_draft': {
          discardPlanBufferedContent();
          const draftTodos = Array.isArray(event.data.todos) ? event.data.todos as PlanTodo[] : [];
          const draftStructured = (event.data.structured_plan ?? null) as StructuredPlanDraft | null;
          chatModeRef.current = 'plan';
          setChatModeState('plan');
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
          discardPlanBufferedContent();
          const questions = Array.isArray(event.data.questions) ? event.data.questions as PlanQuestion[] : [];
          chatModeRef.current = 'plan';
          setChatModeState('plan');
          setPlanState((prev) => ({
            ...prev,
            mode: 'plan',
            questions,
            decisions: {},
            decision_notes: {},
            phase: event.data.phase || 'awaiting_decision',
            pending_clarification:
              typeof event.data.pending_clarification === 'boolean'
                ? event.data.pending_clarification
                : prev.pending_clarification,
          }));
          setMessages((prev) => dropOpenPlanQuestionNoise(prev));
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
          buildRequestInFlightRef.current = false;
          setPlanState((prevPlan) => {
            setMessages((prevMessages) => appendBlock(
              completeOpenThinking(prevMessages),
              {
                type: 'plan_execution',
                goal: prevPlan.goal,
                todos: prevPlan.todos,
                timestamp: Date.now(),
              },
              false,
            ));
            return {
              ...prevPlan,
              phase: 'executing',
            };
          });
          addTerminalLog('[计划] Build 已启动，进入执行阶段');
          break;

        case 'build_paused':
          buildRequestInFlightRef.current = false;
          setIsRunning(false);
          setPlanState((prev) => ({
            ...prev,
            ...event.data,
            todos: Array.isArray(event.data.todos) ? event.data.todos as PlanTodo[] : prev.todos,
            phase: 'approved_waiting_build',
            approved: true,
          }));
          addTerminalLog('[Plan] Build paused');
          break;

        case 'build_ended':
          buildRequestInFlightRef.current = false;
          setIsRunning(false);
          setPlanState((prev) => ({
            ...prev,
            ...event.data,
            todos: Array.isArray(event.data.todos) ? event.data.todos as PlanTodo[] : prev.todos,
            phase: event.data.phase || 'awaiting_approval',
            approved: false,
          }));
          addTerminalLog('[Plan] Build ended');
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

        case 'task_guidance_queued': {
          const incoming = Array.isArray(event.data?.items)
            ? event.data.items as TaskGuidanceItem[]
            : event.data?.item
              ? [event.data.item as TaskGuidanceItem]
              : [];
          setTaskGuidanceItems((prev) => mergeTaskGuidanceItems(prev, incoming));
          addTerminalLog(`[Guidance] Queued ${event.data?.item?.id || 'message'}`);
          break;
        }

        case 'task_guidance_applied': {
          const incoming = Array.isArray(event.data?.all_items)
            ? event.data.all_items as TaskGuidanceItem[]
            : Array.isArray(event.data?.items)
              ? event.data.items as TaskGuidanceItem[]
              : [];
          setTaskGuidanceItems((prev) => mergeTaskGuidanceItems(prev, incoming));
          addTerminalLog(`[Guidance] Applied ${Array.isArray(event.data?.items) ? event.data.items.length : 0} item(s)`);
          break;
        }

        case 'task_guidance_consumed': {
          const consumed = Array.isArray(event.data?.items) ? event.data.items as TaskGuidanceItem[] : [];
          const consumedIds = new Set(consumed.map((item) => item.id));
          setTaskGuidanceItems((prev) => prev.filter((item) => !consumedIds.has(item.id)));
          if (consumed.length > 0) {
            addTerminalLog(`[Guidance] Agent read ${consumed.length} item(s)`);
          }
          break;
        }

        case 'task_guidance_stale': {
          const incoming = Array.isArray(event.data?.all_items)
            ? event.data.all_items as TaskGuidanceItem[]
            : Array.isArray(event.data?.items)
              ? event.data.items as TaskGuidanceItem[]
              : [];
          setTaskGuidanceItems((prev) => mergeTaskGuidanceItems(prev, incoming));
          addTerminalLog('[Guidance] Current run ended before reading guidance');
          break;
        }

        case 'task_guidance_deleted':
          setTaskGuidanceItems((prev) => prev.filter((item) => item.id !== event.data?.id));
          break;

        case 'task_guidance_cleared':
          setTaskGuidanceItems([]);
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
          buildRequestInFlightRef.current = false;
          const msg = errorMessage(event.data);
          const retryable = isRetryableError(event.data);
          setMessages((prev) => {
            const complete = markTurnComplete(completeOpenThinking(prev));
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

        case 'context_usage':
          setContextUsage(event.data as ContextUsage);
          break;

        case 'compacted':
          setIsRunning(false);
          if (event.data?.skipped) {
            if (event.data?.context_usage) {
              setContextUsage(event.data.context_usage as ContextUsage);
            }
            addTerminalLog(`[Context] ${event.data.message || 'Current context does not need compaction yet'}`);
            break;
          }
          if (event.data?.context_usage) {
            setContextUsage(event.data.context_usage as ContextUsage);
          }
          addTerminalLog(`[压缩] 对话已压缩，从 ${event.data.message_count || '?'} 条消息中提取摘要`);
          break;

        case 'rewound':
          if (event.data?.context_usage) {
            setContextUsage(event.data.context_usage as ContextUsage);
          }
          addTerminalLog(`[Rewind] Restored checkpoint ${event.data?.checkpoint_id || ''}`);
          break;

        case 'model_switched':
          addTerminalLog(`[模型] 已切换至 ${event.data.model_id}`);
          break;

        case 'agent_switched': {
          const intensity = event.data?.thinking_intensity;
          if (isThinkingIntensity(intensity)) {
            setThinkingIntensityState(intensity);
          }
          addTerminalLog(`[Agent] ${event.data?.name || event.data?.agent_type || 'switched'}`);
          break;
        }

        case 'done':
          setIsRunning(false);
          setMessages((prev) => markTurnComplete(completeOpenThinking(prev)));
          break;

        case 'cleared':
          buildRequestInFlightRef.current = false;
          discardPlanBufferedContent();
          setMessages([]);
          setToolCalls([]);
          setFileEdits([]);
          setRunEvents([]);
          setContextUsage(null);
          setCheckpoints([]);
          setTaskGuidanceItems([]);
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
            decision_notes: {},
            approved: false,
            pending_clarification: false,
            plan_file_path: null,
            research_notes: '',
          });
          addTerminalLog('[系统] 会话已清空');
          break;

        case 'interrupted':
          buildRequestInFlightRef.current = false;
          setIsRunning(false);
          setMessages((prev) => markTurnComplete(completeOpenThinking(prev)));
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
    [
      addTerminalLog,
      attachWorkerEvent,
      discardPlanBufferedContent,
      flushPlanBufferedContent,
      recordFileEdit,
      recordRunEvent,
      sessionId,
      shouldBufferPlanContent,
      takePendingWorkerEvents,
    ]
  );

  const { isConnected, send, disconnect } = useWebSocket(sessionId, handleMessage);

  useLayoutEffect(() => {
    sendRef.current = send;
  }, [send]);

  const setChatMode = useCallback((mode: ClientChatMode) => {
    chatModeRef.current = mode;
    setChatModeState(mode);
    sendRef.current({ type: 'set_chat_mode', chat_mode: mode });
  }, []);

  const setThinkingIntensity = useCallback((intensity: ThinkingIntensity) => {
    setThinkingIntensityState(intensity);
    thinkingIntensityRef.current = intensity;
    sendRef.current({ type: 'set_thinking_intensity', thinking_intensity: intensity });
  }, []);

  useEffect(() => {
    if (!isConnected) return;
    send({ type: 'set_chat_mode', chat_mode: chatModeRef.current });
    send({ type: 'set_thinking_intensity', thinking_intensity: thinkingIntensityRef.current });
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
        const cachedMessages = sanitizeThinkingPlaceholders(sanitizeCachedMessages(data.messages || []));
        if (cachedMessages.length > 0) {
          setMessages(cachedMessages);
        }
        setToolCalls(data.toolCalls || []);
        setFileEdits(data.fileEdits || []);
        setTaskGuidanceItems(Array.isArray(data.taskGuidanceItems) ? data.taskGuidanceItems as TaskGuidanceItem[] : []);
        if (data.chatMode === 'plan' || data.chatMode === 'agent') {
          setChatModeState(data.chatMode);
        }
        if (isThinkingIntensity(data.thinkingIntensity)) {
          setThinkingIntensityState(data.thinkingIntensity);
        }
        if (data.planState) {
          setPlanState((prev) => ({ ...prev, ...data.planState }));
        }
      }

      try {
        const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`);
        const snapshot = await res.json();
        if (!mounted || userTouchedRef.current || snapshot?.error) return;
        const restored = sessionSnapshotToState(snapshot);
        setMessages((prev) => mergeSnapshotWithOptimistic(prev, restored.messages));
        setToolCalls(restored.toolCalls);
        setFileEdits([]);
        if (restored.chatMode) setChatModeState(restored.chatMode);
        if (restored.thinkingIntensity) setThinkingIntensityState(restored.thinkingIntensity);
        if (restored.planState) setPlanState((prev) => ({ ...prev, ...restored.planState }));
        setContextUsage(restored.contextUsage || null);
        setCheckpoints(restored.checkpoints || []);
        setTaskGuidanceItems(restored.taskGuidanceItems || []);
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
        taskGuidanceItems,
      }).catch(console.error);
    }, 1000);
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, [sessionId, hydratedSessionId, messages, toolCalls, fileEdits, chatMode, thinkingIntensity, planState, taskGuidanceItems]);

  const queueTaskGuidance = useCallback(
    (text: string, imageBase64?: string) => {
      if (!text.trim() && !imageBase64) return false;
      const sent = send({
        type: 'queue_task_guidance',
        text: text.trim(),
        image_base64: imageBase64,
      });
      if (sent === false) {
        addTerminalLog('[错误] WebSocket 未连接，引导消息未排队');
        return false;
      }
      return true;
    },
    [send, addTerminalLog],
  );

  const applyTaskGuidance = useCallback(() => {
    const sent = send({ type: 'apply_task_guidance' });
    if (sent === false) {
      addTerminalLog('[错误] WebSocket 未连接，任务引导未发送');
    }
  }, [send, addTerminalLog]);

  const deleteTaskGuidance = useCallback((id: string) => {
    if (!id) return;
    const sent = send({ type: 'delete_task_guidance', id });
    if (sent === false) {
      setTaskGuidanceItems((prev) => prev.filter((item) => item.id !== id));
    }
  }, [send]);

  const clearTaskGuidance = useCallback(() => {
    const sent = send({ type: 'clear_task_guidance' });
    if (sent === false) {
      setTaskGuidanceItems([]);
    }
  }, [send]);

  const sendMessage = useCallback(
    (text: string, imageBase64?: string, overrides?: { chatMode?: ClientChatMode; thinkingIntensity?: ThinkingIntensity }) => {
      if (!text.trim() && !imageBase64) return;
      if (!currentModel) {
        addTerminalLog('[错误] 模型未加载，请等待页面加载完成');
        return;
      }
      if (isRunningRef.current) {
        queueTaskGuidance(text, imageBase64);
        return;
      }
      userTouchedRef.current = true;
      setHydratedSessionId(sessionId);
      isRunningRef.current = true;
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
        chat_mode: overrides?.chatMode || chatModeRef.current,
        thinking_intensity: overrides?.thinkingIntensity || thinkingIntensityRef.current,
      });
      if (sent === false) {
        isRunningRef.current = false;
        setIsRunning(false);
        addTerminalLog('[错误] WebSocket 未连接，消息未发送');
      }
    },
    [send, sessionId, currentModel, agentType, roleId, addTerminalLog, queueTaskGuidance]
  );

  const clearSession = useCallback(() => {
    send({ type: 'clear' });
    setIsRunning(false);
  }, [send]);

  const compactSession = useCallback((force = false, focus = '') => {
    setIsRunning(true);
    const sent = send({ type: 'compact', force, focus, source: 'ui' });
    if (sent === false) setIsRunning(false);
  }, [send]);

  const loadCheckpoints = useCallback(async (): Promise<ConversationCheckpoint[]> => {
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/checkpoints`);
      const data = await res.json();
      const next = Array.isArray(data.checkpoints) ? data.checkpoints as ConversationCheckpoint[] : [];
      setCheckpoints(next);
      return next;
    } catch (err) {
      addTerminalLog(`[Rewind] Failed to load checkpoints: ${err}`);
      return [];
    }
  }, [sessionId, addTerminalLog]);

  const rewindToCheckpoint = useCallback((checkpointId: string) => {
    if (!checkpointId) return;
    setIsRunning(true);
    const sent = send({
      type: 'rewind',
      checkpoint_id: checkpointId,
      retry: true,
      model_id: currentModel,
      agent_type: agentType,
      role_id: roleId,
      chat_mode: chatModeRef.current,
      thinking_intensity: thinkingIntensity,
    });
    if (sent === false) setIsRunning(false);
  }, [send, currentModel, agentType, roleId, thinkingIntensity]);

  const stopRunning = useCallback(() => {
    send({ type: 'stop' });
  }, [send]);

  const retryLast = useCallback(() => {
    send({
      type: 'retry',
      model_id: currentModel,
      agent_type: agentType,
      role_id: roleId,
      chat_mode: chatModeRef.current,
      thinking_intensity: thinkingIntensity,
    });
    setIsRunning(true);
  }, [send, currentModel, agentType, roleId, thinkingIntensity]);

  const switchModel = useCallback((modelId: string) => {
    if (!modelId) return;
    send({ type: 'switch_model', model_id: modelId });
  }, [send]);

  const switchRole = useCallback((roleId: string) => {
    if (!roleId) return;
    send({ type: 'switch_role', role_id: roleId });
  }, [send]);

  const approvePlan = useCallback(() => {
    setIsRunning(false);
    send({ type: 'approve_plan' });
  }, [send]);

  const buildPlan = useCallback(() => {
    if (buildRequestInFlightRef.current) {
      addTerminalLog('[Plan] Build already requested');
      return;
    }
    const snapshot = planStateRef.current;
    const hasPlan = !!(snapshot.draft || snapshot.structured_plan || snapshot.todos.length > 0);
    const buildable = snapshot.phase === 'awaiting_approval' || snapshot.phase === 'approved_waiting_build';
    if (!hasPlan || !buildable) {
      addTerminalLog('[Plan] Build ignored: no approved plan draft is ready');
      return;
    }
    buildRequestInFlightRef.current = true;
    const sent = send({ type: 'build_plan', plan_state: snapshot });
    if (!sent) {
      buildRequestInFlightRef.current = false;
      return;
    }
    setIsRunning(true);
    setPlanState((prev) => ({
      ...prev,
      approved: true,
      phase: 'approved_waiting_build',
    }));
  }, [addTerminalLog, send]);

  const pauseBuild = useCallback(() => {
    setIsRunning(false);
    setPlanState((prev) => ({
      ...prev,
      approved: true,
      phase: 'approved_waiting_build',
      todos: prev.todos.map((todo) => (
        todo.status === 'in_progress' ? { ...todo, status: 'pending' as const } : todo
      )),
    }));
    send({ type: 'pause_build' });
  }, [send]);

  const endBuild = useCallback(() => {
    setIsRunning(false);
    setPlanState((prev) => ({
      ...prev,
      approved: false,
      phase: prev.draft || prev.structured_plan ? 'awaiting_approval' : 'idle',
      todos: prev.todos.map((todo) => (
        todo.status === 'pending' || todo.status === 'in_progress'
          ? { ...todo, status: 'cancelled' as const }
          : todo
      )),
    }));
    send({ type: 'end_build' });
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

  const submitPlanDecisions = useCallback((answers: PlanDecisionAnswer[]) => {
    const normalized = answers.map((answer) => ({
      question_id: answer.question_id,
      selected: Array.isArray(answer.selected) ? answer.selected : [],
      other_text: answer.other_text || '',
      skipped: !!answer.skipped,
    }));
    setPlanState((prev) => {
      const decisions = { ...prev.decisions };
      const decisionNotes = { ...(prev.decision_notes || {}) };
      for (const answer of normalized) {
        decisions[answer.question_id] = answer.selected;
        const notes: string[] = [];
        if (answer.other_text.trim()) notes.push(`Other: ${answer.other_text.trim()}`);
        if (answer.skipped) notes.push('Skipped');
        if (notes.length > 0) decisionNotes[answer.question_id] = notes.join('; ');
      }
      return {
        ...prev,
        phase: 'planning',
        pending_clarification: false,
        decisions,
        decision_notes: decisionNotes,
      };
    });
    setIsRunning(true);
    const sent = send({ type: 'submit_plan_decisions', answers: normalized });
    if (sent === false) {
      setIsRunning(false);
      addTerminalLog('[错误] WebSocket 未连接，计划选择未发送');
    }
  }, [addTerminalLog, send]);

  const executeToolDirect = useCallback(
    (toolName: string, args: any) => {
      send({ type: 'tool_direct', tool_name: toolName, args });
    },
    [send]
  );

  const resetSession = useCallback(() => {
    disconnect();
    userTouchedRef.current = false;
    buildRequestInFlightRef.current = false;
    discardPlanBufferedContent();
    setHydratedSessionId('');
    setMessages([]);
    setToolCalls([]);
    setFileEdits([]);
    setRunEvents([]);
    setContextUsage(null);
    setCheckpoints([]);
    setTaskGuidanceItems([]);
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
      decision_notes: {},
      approved: false,
      pending_clarification: false,
      plan_file_path: null,
      research_notes: '',
    });
  }, [discardPlanBufferedContent, disconnect]);

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
    contextUsage,
    checkpoints,
    taskGuidanceItems,
    terminalLogs,
    isRunning,
    isConnected,
    sendMessage,
    queueTaskGuidance,
    applyTaskGuidance,
    deleteTaskGuidance,
    clearTaskGuidance,
    clearSession,
    compactSession,
    loadCheckpoints,
    rewindToCheckpoint,
    stopRunning,
    retryLast,
    switchModel,
    switchRole,
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
    pauseBuild,
    endBuild,
    rejectPlan,
    updatePlanDecision,
    submitPlanDecisions,
    suggestAgentSwitch,
    clearSuggestAgentSwitch,
  };
}
