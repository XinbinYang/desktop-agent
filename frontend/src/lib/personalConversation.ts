import type {
  AssistantBlock,
  ChatMessage,
  FileEdit,
  KnowledgeContextSource,
  PlanState,
  ToolCall,
  WorkerEvent,
} from '../types';
import { isInternalToolName } from './internalTools';

export type PersonalConversationRole = 'user' | 'assistant' | 'system';
export type PersonalActivityKind = 'thinking' | 'tool' | 'knowledge' | 'file_edit' | 'plan';
export type PersonalActivityStatus = 'running' | 'success' | 'error' | 'neutral';

export interface PersonalActivityTool {
  id: string;
  name: string;
  args: Record<string, any>;
  result?: string;
  status: 'running' | 'success' | 'error';
  timestamp?: number;
  durationMs?: number;
  workerEvents?: WorkerEvent[];
  toolCallId?: string;
}

export interface PersonalActivityItem {
  id: string;
  kind: PersonalActivityKind;
  label: string;
  status: PersonalActivityStatus;
  timestamp?: number;
  text?: string;
  tools?: PersonalActivityTool[];
  sources?: KnowledgeContextSource[];
  edit?: FileEdit;
  count?: number;
}

export interface PersonalConversationItem {
  id: string;
  role: PersonalConversationRole;
  authorName: string;
  text: string;
  images: string[];
  activities: PersonalActivityItem[];
  createdAt?: number;
  messageId?: string;
  checkpointId?: string;
  source?: string;
  noticeLevel?: 'success' | 'info' | 'warning' | 'error';
  turnComplete?: boolean;
  isStreaming: boolean;
}

export interface PersonalMessageGroup {
  id: string;
  role: PersonalConversationRole;
  authorName: string;
  startedAt?: number;
  endedAt?: number;
  items: PersonalConversationItem[];
}

export interface BuildPersonalConversationInput {
  messages: ChatMessage[];
  toolCalls?: ToolCall[];
  fileEdits?: FileEdit[];
  planState?: PlanState;
  assistantDisplayName?: string;
}

const GROUP_WINDOW_MS = 5 * 60 * 1000;
const MIN_REAL_TIMESTAMP_MS = Date.UTC(2000, 0, 1);

function roleAuthor(role: PersonalConversationRole, assistantDisplayName = 'Personal Agent'): string {
  if (role === 'user') return 'You';
  if (role === 'system') return 'System';
  return assistantDisplayName.trim() || 'Personal Agent';
}

function formatDuration(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  if (totalSec < 60) return `${totalSec}s`;
  const minutes = Math.floor(totalSec / 60);
  const seconds = totalSec % 60;
  return seconds === 0 ? `${minutes}m` : `${minutes}m ${seconds}s`;
}

function normalizeTimestamp(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= MIN_REAL_TIMESTAMP_MS
    ? value
    : undefined;
}

function messageTimestamp(message: ChatMessage): number | undefined {
  return normalizeTimestamp(message.createdAt);
}

function firstBlockTimestamp(message: ChatMessage): number | undefined {
  for (const block of message.blocks || []) {
    const timestamp = normalizeTimestamp(block.timestamp);
    if (timestamp !== undefined) return timestamp;
  }
  return undefined;
}

function blockTimestamp(message: ChatMessage, block?: { timestamp?: number }): number | undefined {
  return normalizeTimestamp(block?.timestamp) ?? messageTimestamp(message);
}

function firstDefinedTimestamp(values: Array<number | undefined>): number | undefined {
  return values.find((value) => value !== undefined);
}

function latestTimestamp(values: Array<number | undefined>): number | undefined {
  const valid = values.filter((value): value is number => value !== undefined);
  return valid.length > 0 ? Math.max(...valid) : undefined;
}

function firstStringArg(args: Record<string, any>, keys: string[]): string {
  for (const key of keys) {
    const value = args?.[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function toolLabel(name: string, args: Record<string, any>): string {
  const n = (name || '').toLowerCase();
  if (n.includes('dispatch') || n.includes('worker') || n.includes('agent')) return 'Agent';
  if (n.includes('shell') || n.includes('bash') || n.includes('terminal')) return 'Bash';
  if (n.includes('read')) return 'Read';
  if (n.includes('search') || n.includes('grep')) return 'Search';
  if (n.includes('list')) return 'List';
  if (n.includes('write') || n.includes('edit') || n.includes('patch')) return 'Edit';
  if (n.includes('browser')) return 'Browser';
  if (n.includes('web')) return 'Web';
  return name || firstStringArg(args, ['tool', 'name']) || 'Tool';
}

function toolTarget(name: string, args: Record<string, any>): string {
  const n = (name || '').toLowerCase();
  if (n.includes('dispatch') || n.includes('worker') || n.includes('agent')) {
    const tasks = Array.isArray(args?.tasks) ? args.tasks.length : 0;
    if (tasks > 0) return `${tasks} agent${tasks > 1 ? 's' : ''}`;
    return firstStringArg(args, ['task', 'goal', 'prompt']);
  }
  if (n.includes('shell') || n.includes('bash') || n.includes('terminal')) {
    return firstStringArg(args, ['command', 'cmd', 'script', 'shell', 'input']);
  }
  return firstStringArg(args, ['path', 'file', 'file_path', 'query', 'url', 'command']);
}

function toActivityTool(
  block: Extract<AssistantBlock, { type: 'tool_call' }>,
  index: number,
): PersonalActivityTool {
  return {
    id: block.toolCallId || `${block.name}:${block.timestamp}:${index}`,
    name: block.name,
    args: block.args || {},
    result: block.result,
    status: block.status,
    timestamp: normalizeTimestamp(block.timestamp),
    durationMs: block.durationMs,
    workerEvents: block.workerEvents,
    toolCallId: block.toolCallId,
  };
}

function toolCallToActivityTool(call: ToolCall, index: number): PersonalActivityTool {
  const status = call.result?.startsWith('[ERROR]') ? 'error' : 'success';
  return {
    id: call.toolCallId || `${call.name}:${call.timestamp || index}:${index}`,
    name: call.name,
    args: call.args || {},
    result: call.result,
    status,
    timestamp: normalizeTimestamp(call.timestamp),
    durationMs: call.durationMs,
    workerEvents: call.workerEvents,
    toolCallId: call.toolCallId,
  };
}

function summarizeToolActivity(
  id: string,
  tools: PersonalActivityTool[],
  timestamp?: number,
): PersonalActivityItem | null {
  if (tools.length === 0) return null;
  const status: PersonalActivityStatus = tools.some((tool) => tool.status === 'error')
    ? 'error'
    : tools.some((tool) => tool.status === 'running')
      ? 'running'
      : 'success';
  const labels = new Set(tools.map((tool) => toolLabel(tool.name, tool.args)));
  const first = tools[0];
  const target = tools.length === 1 ? toolTarget(first.name, first.args) : '';
  const singleLabel = target ? `${toolLabel(first.name, first.args)} ${target}` : toolLabel(first.name, first.args);
  const label = tools.length === 1
    ? (status === 'running' ? `Using ${singleLabel}` : `Used ${singleLabel}`)
    : status === 'running'
      ? `Using ${tools.length} tools`
      : labels.size === 1
        ? `Used ${tools.length} ${[...labels][0]} calls`
        : `Used ${tools.length} tools`;

  return {
    id,
    kind: 'tool',
    label,
    status,
    timestamp,
    tools,
    count: tools.length,
  };
}

function pushToolSummary(
  activities: PersonalActivityItem[],
  tools: PersonalActivityTool[],
  message: ChatMessage,
) {
  const summary = summarizeToolActivity(
    `tools:${message.id}:${tools.map((tool) => tool.id).join('|')}`,
    tools,
    latestTimestamp([...tools.map((tool) => tool.timestamp), messageTimestamp(message)]),
  );
  if (summary) activities.push(summary);
}

function activityStatusFromPlan(phase?: PlanState['phase']): PersonalActivityStatus {
  if (phase === 'executing' || phase === 'planning') return 'running';
  if (phase === 'completed') return 'success';
  return 'neutral';
}

// Cache per-assistant-message build results so that streaming-token-triggered
// re-renders only recompute the one message whose text is actively growing.
// Key = message.id; value's signature captures the inputs that affect output
// (turnComplete, content length, reasoning presence, per-block fingerprints,
// planState phase, and which toolCallIds/editIds have already been claimed
// elsewhere — so the fallback paths stay correct).
interface AssistantCacheEntry {
  signature: string;
  toolIds: string[];
  editIds: string[];
  item: PersonalConversationItem | null;
}
const assistantItemCache = new Map<string, AssistantCacheEntry>();
const ASSISTANT_CACHE_MAX = 256;

function rememberAssistantCache(messageId: string, entry: AssistantCacheEntry) {
  assistantItemCache.delete(messageId);
  assistantItemCache.set(messageId, entry);
  while (assistantItemCache.size > ASSISTANT_CACHE_MAX) {
    const oldestKey = assistantItemCache.keys().next().value;
    if (oldestKey === undefined) break;
    assistantItemCache.delete(oldestKey);
  }
}

function buildAssistantSignature(
  message: ChatMessage,
  planState?: PlanState,
  assistantDisplayName?: string,
): string {
  const blocks = message.blocks || [];
  const blockParts: string[] = [];
  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];
    switch (block.type) {
      case 'text':
        blockParts.push(`x:${(block.text || '').length}`);
        break;
      case 'thinking':
        blockParts.push(
          `k:${block.complete ? 1 : 0}:${(block.text || '').length}:${block.startedAt || 0}:${block.endedAt || 0}`,
        );
        break;
      case 'tool_call':
        blockParts.push(
          `t:${block.toolCallId || ''}:${block.status}:${(block.result || '').length}:${block.durationMs || 0}`,
        );
        break;
      case 'file_edit':
        blockParts.push(`e:${block.edit.tool_call_id || block.edit.path}:${block.edit.timestamp || 0}`);
        break;
      case 'knowledge_context':
        blockParts.push(`g:${block.sources.length}`);
        break;
      case 'image':
        blockParts.push(`i:${block.base64?.length || 0}`);
        break;
      case 'plan_execution':
      case 'plan_draft':
        blockParts.push(`p:${block.type}:${block.todos?.length || 0}:${block.goal || ''}`);
        break;
      default:
        blockParts.push((block as { type?: string }).type || '?');
        break;
    }
  }
  return [
    message.turnComplete ? 1 : 0,
    (message.content || '').length,
    message.reasoning ? (message.reasoning || '').length : 0,
    message.messageId || '',
    message.checkpointId || '',
    planState?.phase || '',
    planState?.goal || '',
    assistantDisplayName || '',
    blockParts.join('|'),
  ].join('§');
}

function buildAssistantItem(
  message: ChatMessage,
  seenToolIds: Set<string>,
  seenEditIds: Set<string>,
  planState?: PlanState,
  assistantDisplayName?: string,
): PersonalConversationItem | null {
  const cached = assistantItemCache.get(message.id);
  const signature = buildAssistantSignature(message, planState, assistantDisplayName);
  if (cached && cached.signature === signature) {
    // Re-claim ids in the live seen sets so fallback merging stays correct.
    for (const toolId of cached.toolIds) seenToolIds.add(toolId);
    for (const editId of cached.editIds) seenEditIds.add(editId);
    rememberAssistantCache(message.id, cached);
    return cached.item;
  }

  const claimedTools: string[] = [];
  const claimedEdits: string[] = [];
  const item = buildAssistantItemUncached(
    message,
    seenToolIds,
    seenEditIds,
    planState,
    assistantDisplayName,
    claimedTools,
    claimedEdits,
  );
  rememberAssistantCache(message.id, {
    signature,
    toolIds: claimedTools,
    editIds: claimedEdits,
    item,
  });
  return item;
}

function buildAssistantItemUncached(
  message: ChatMessage,
  seenToolIds: Set<string>,
  seenEditIds: Set<string>,
  planState: PlanState | undefined,
  assistantDisplayName: string | undefined,
  claimedTools: string[],
  claimedEdits: string[],
): PersonalConversationItem | null {
  const textParts: string[] = [];
  const images: string[] = [];
  const activities: PersonalActivityItem[] = [];
  const tools: PersonalActivityTool[] = [];
  const blocks = message.blocks || [];

  if (message.reasoning) {
    activities.push({
      id: `thinking:${message.id}:legacy`,
      kind: 'thinking',
      label: message.turnComplete === false ? 'Thinking' : 'Thought',
      status: message.turnComplete === false ? 'running' : 'neutral',
      timestamp: messageTimestamp(message),
      text: message.reasoning,
    });
  }

  blocks.forEach((block, blockIndex) => {
    const timestamp = blockTimestamp(message, block);
    const idTimestamp = timestamp ?? block.timestamp ?? blockIndex;
    switch (block.type) {
      case 'thinking':
        const thoughtEndedAt = typeof block.endedAt === 'number'
          ? block.endedAt
          : typeof block.timestamp === 'number'
            ? block.timestamp
            : undefined;
        const elapsedLabel = block.complete && typeof block.startedAt === 'number' && thoughtEndedAt !== undefined
          ? `Thought for ${formatDuration(thoughtEndedAt - block.startedAt)}`
          : undefined;
        activities.push({
          id: `thinking:${message.id}:${idTimestamp}:${blockIndex}`,
          kind: 'thinking',
          label: block.complete ? (elapsedLabel || 'Thought') : 'Thinking',
          status: block.complete ? 'neutral' : 'running',
          timestamp,
          text: block.text,
        });
        break;
      case 'text':
        if (block.text.trim()) textParts.push(block.text);
        break;
      case 'knowledge_context':
        activities.push({
          id: `knowledge:${message.id}:${idTimestamp}:${blockIndex}`,
          kind: 'knowledge',
          label: `Used ${block.sources.length} memory source${block.sources.length === 1 ? '' : 's'}`,
          status: 'neutral',
          timestamp,
          sources: block.sources,
          count: block.sources.length,
        });
        break;
      case 'tool_call':
        if (!isInternalToolName(block.name)) {
          const tool = toActivityTool(block, blockIndex);
          if (tool.toolCallId) {
            seenToolIds.add(tool.toolCallId);
            claimedTools.push(tool.toolCallId);
          }
          tools.push(tool);
        }
        break;
      case 'file_edit':
        if (block.edit.tool_call_id) {
          seenEditIds.add(block.edit.tool_call_id);
          claimedEdits.push(block.edit.tool_call_id);
        }
        activities.push({
          id: `edit:${block.edit.tool_call_id || `${message.id}:${idTimestamp}:${blockIndex}`}`,
          kind: 'file_edit',
          label: `${block.edit.operation || 'Edited'} ${block.edit.path}`,
          status: 'success',
          timestamp,
          edit: block.edit,
        });
        break;
      case 'image':
        images.push(block.base64);
        break;
      case 'plan_execution':
        activities.push({
          id: `plan-execution:${message.id}:${idTimestamp}:${blockIndex}`,
          kind: 'plan',
          label: block.goal || planState?.goal || 'Plan execution',
          status: activityStatusFromPlan(planState?.phase),
          timestamp,
          count: block.todos.length,
        });
        break;
      case 'plan_draft':
        activities.push({
          id: `plan-draft:${message.id}:${idTimestamp}:${blockIndex}`,
          kind: 'plan',
          label: block.goal || 'Plan draft ready',
          status: activityStatusFromPlan(planState?.phase),
          timestamp,
          count: block.todos.length,
        });
        break;
      default:
        break;
    }
  });

  if (tools.length > 0) {
    pushToolSummary(activities, tools, message);
  }

  const fallbackText = message.content?.trim() ? message.content : '';
  const text = textParts.length > 0 ? textParts.join('\n\n') : fallbackText;
  if (!text.trim() && images.length === 0 && activities.length === 0) return null;

  return {
    id: `personal:${message.id}`,
    role: 'assistant',
    authorName: roleAuthor('assistant', assistantDisplayName),
    text,
    images,
    activities: activities.sort((a, b) => {
      if (a.timestamp === undefined || b.timestamp === undefined) return 0;
      return a.timestamp - b.timestamp;
    }),
    createdAt: messageTimestamp(message) ?? firstBlockTimestamp(message),
    messageId: message.messageId,
    checkpointId: message.checkpointId,
    turnComplete: message.turnComplete,
    isStreaming: message.turnComplete === false,
  };
}

function appendFallbackToolActivity(
  items: PersonalConversationItem[],
  toolCalls: ToolCall[] = [],
  seenToolIds: Set<string>,
  assistantDisplayName?: string,
) {
  const unseen = toolCalls
    .filter((call) => !call.toolCallId || !seenToolIds.has(call.toolCallId))
    .map(toolCallToActivityTool);
  if (unseen.length === 0) return;
  const latestAssistant = [...items].reverse().find((item) => item.role === 'assistant');
  const target = latestAssistant || {
    id: `personal:fallback-tools:${unseen.map((tool) => tool.id).join('|') || 'untracked'}`,
    role: 'assistant' as const,
    authorName: roleAuthor('assistant', assistantDisplayName),
    text: '',
    images: [],
    activities: [],
    createdAt: firstDefinedTimestamp(unseen.map((tool) => tool.timestamp)),
    turnComplete: true,
    isStreaming: false,
  };
  const activity = summarizeToolActivity(
    `tools:fallback:${unseen.map((tool) => tool.id).join('|')}`,
    unseen,
    latestTimestamp(unseen.map((tool) => tool.timestamp)),
  );
  if (activity) target.activities.push(activity);
  if (!latestAssistant) items.push(target);
}

function appendFallbackFileEdits(
  items: PersonalConversationItem[],
  fileEdits: FileEdit[] = [],
  seenEditIds: Set<string>,
  assistantDisplayName?: string,
) {
  const unseen = fileEdits.filter((edit) => !edit.tool_call_id || !seenEditIds.has(edit.tool_call_id));
  if (unseen.length === 0) return;
  const latestAssistant = [...items].reverse().find((item) => item.role === 'assistant');
  const editTimestamps = unseen.map((edit) => normalizeTimestamp(edit.timestamp));
  const target = latestAssistant || {
    id: `personal:fallback-edits:${unseen.map((edit) => edit.tool_call_id || edit.path).join('|') || 'untracked'}`,
    role: 'assistant' as const,
    authorName: roleAuthor('assistant', assistantDisplayName),
    text: '',
    images: [],
    activities: [],
    createdAt: firstDefinedTimestamp(editTimestamps),
    turnComplete: true,
    isStreaming: false,
  };
  unseen.forEach((edit, index) => {
    const timestamp = normalizeTimestamp(edit.timestamp);
    target.activities.push({
      id: `edit:${edit.tool_call_id || `${edit.path}:${edit.timestamp || index}`}`,
      kind: 'file_edit',
      label: `${edit.operation || 'Edited'} ${edit.path}`,
      status: 'success',
      timestamp,
      edit,
    });
  });
  if (!latestAssistant) items.push(target);
}

function groupItems(items: PersonalConversationItem[]): PersonalMessageGroup[] {
  const groups: PersonalMessageGroup[] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    const sameAuthor = last?.role === item.role && last.authorName === item.authorName;
    const closeEnough = last
      ? item.createdAt === undefined || last.endedAt === undefined || Math.abs(item.createdAt - last.endedAt) <= GROUP_WINDOW_MS
      : false;
    if (last && sameAuthor && closeEnough) {
      last.items.push(item);
      last.startedAt = last.startedAt ?? item.createdAt;
      last.endedAt = item.createdAt ?? last.endedAt;
      continue;
    }
    groups.push({
      id: `group:${item.id}`,
      role: item.role,
      authorName: item.authorName,
      startedAt: item.createdAt,
      endedAt: item.createdAt,
      items: [item],
    });
  }
  return groups;
}

export function buildPersonalConversation({
  messages,
  toolCalls = [],
  fileEdits = [],
  planState,
  assistantDisplayName = 'Personal Agent',
}: BuildPersonalConversationInput): PersonalMessageGroup[] {
  const items: PersonalConversationItem[] = [];
  const seenToolIds = new Set<string>();
  const seenEditIds = new Set<string>();

  messages.filter(Boolean).forEach((message) => {
    if (message.role === 'user') {
      if (!message.content.trim() && !message.imageBase64) return;
      items.push({
        id: `personal:${message.id}`,
        role: 'user',
        authorName: roleAuthor('user'),
        text: message.content,
        images: message.imageBase64 ? [message.imageBase64] : [],
        activities: [],
        createdAt: messageTimestamp(message),
        messageId: message.messageId,
        checkpointId: message.checkpointId,
        source: message.source,
        noticeLevel: message.noticeLevel,
        turnComplete: true,
        isStreaming: false,
      });
      return;
    }

    if (message.role === 'system') {
      if (!message.content.trim()) return;
      items.push({
        id: `personal:${message.id}`,
        role: 'system',
        authorName: roleAuthor('system'),
        text: message.content,
        images: [],
        activities: [],
        createdAt: messageTimestamp(message),
        messageId: message.messageId,
        checkpointId: message.checkpointId,
        source: message.source,
        noticeLevel: message.noticeLevel,
        turnComplete: true,
        isStreaming: false,
      });
      return;
    }

    const assistantItem = buildAssistantItem(message, seenToolIds, seenEditIds, planState, assistantDisplayName);
    if (assistantItem) items.push(assistantItem);
  });

  appendFallbackToolActivity(items, toolCalls, seenToolIds, assistantDisplayName);
  appendFallbackFileEdits(items, fileEdits, seenEditIds, assistantDisplayName);

  return groupItems(items);
}
