import type {
  AssistantBlock,
  ChatMessage,
  FileEdit,
  KnowledgeContextSource,
  PlanState,
  PlanTodo,
  RunEvent,
  ToolCall,
  WorkerEvent,
} from '../types';
import { filterVisibleToolCalls, isInternalToolName } from './internalTools';

export type TimelineEventKind =
  | 'user'
  | 'thinking'
  | 'text_summary'
  | 'tool'
  | 'file_edit'
  | 'todo'
  | 'knowledge'
  | 'image'
  | 'error'
  | 'run_status';

export type TimelineRenderMode = 'coding' | 'personal';

type ToolStatus = 'running' | 'success' | 'error';

interface TimelineBaseEvent {
  id: string;
  kind: TimelineEventKind;
  timestamp: number;
  messageId?: string;
}

export interface TimelineToolItem {
  id: string;
  name: string;
  args: Record<string, any>;
  result?: string;
  status: ToolStatus;
  durationMs?: number;
  workerEvents?: WorkerEvent[];
  timestamp: number;
  toolCallId?: string;
}

export interface TimelineUserEvent extends TimelineBaseEvent {
  kind: 'user';
  message: ChatMessage;
  text: string;
  imageBase64?: string;
}

export interface TimelineThinkingEvent extends TimelineBaseEvent {
  kind: 'thinking';
  text: string;
  complete?: boolean;
  startedAt?: number;
  endedAt?: number;
}

export interface TimelineTextEvent extends TimelineBaseEvent {
  kind: 'text_summary';
  text: string;
  role: 'assistant' | 'system';
  message?: ChatMessage;
}

export interface TimelineToolEvent extends TimelineBaseEvent {
  kind: 'tool';
  tools: TimelineToolItem[];
  label: string;
  disclosure?: boolean;
  grouped?: boolean;
  status: ToolStatus;
}

export interface TimelineFileEditEvent extends TimelineBaseEvent {
  kind: 'file_edit';
  edit: FileEdit;
}

export interface TimelineTodoEvent extends TimelineBaseEvent {
  kind: 'todo';
  goal: string;
  todos: PlanTodo[];
  phase?: PlanState['phase'];
  source: 'execution' | 'draft' | 'state';
  planDraft?: Extract<AssistantBlock, { type: 'plan_draft' }>;
  planExecution?: Extract<AssistantBlock, { type: 'plan_execution' }>;
}

export interface TimelineKnowledgeEvent extends TimelineBaseEvent {
  kind: 'knowledge';
  sources: KnowledgeContextSource[];
}

export interface TimelineImageEvent extends TimelineBaseEvent {
  kind: 'image';
  base64: string;
}

export interface TimelineErrorEvent extends TimelineBaseEvent {
  kind: 'error';
  text: string;
}

export interface TimelineRunStatusEvent extends TimelineBaseEvent {
  kind: 'run_status';
  event: RunEvent;
  label: string;
  detail?: string;
}

export type TimelineEvent =
  | TimelineUserEvent
  | TimelineThinkingEvent
  | TimelineTextEvent
  | TimelineToolEvent
  | TimelineFileEditEvent
  | TimelineTodoEvent
  | TimelineKnowledgeEvent
  | TimelineImageEvent
  | TimelineErrorEvent
  | TimelineRunStatusEvent;

export interface BuildTimelineEventsInput {
  messages: ChatMessage[];
  toolCalls?: ToolCall[];
  fileEdits?: FileEdit[];
  runEvents?: RunEvent[];
  planState?: PlanState;
  mode: TimelineRenderMode;
}

function blockTimestamp(message: ChatMessage, block?: { timestamp?: number }, fallback = 0): number {
  return block?.timestamp ?? message.createdAt ?? fallback;
}

function toolEventId(item: TimelineToolItem): string {
  return item.toolCallId || `${item.name}:${item.timestamp}:${stableStringify(item.args).slice(0, 160)}`;
}

function editEventId(edit: FileEdit): string {
  return edit.tool_call_id || `${edit.path}:${edit.timestamp || 0}:${edit.operation}`;
}

function stableStringify(value: unknown): string {
  try {
    return JSON.stringify(value, Object.keys(value as Record<string, unknown> || {}).sort());
  } catch {
    return String(value);
  }
}

function toToolItem(
  block: Extract<AssistantBlock, { type: 'tool_call' }>,
  message: ChatMessage,
  index: number,
): TimelineToolItem {
  return {
    id: block.toolCallId || `${message.id}:tool:${index}:${block.timestamp}`,
    name: block.name,
    args: block.args || {},
    result: block.result,
    status: block.status,
    durationMs: block.durationMs,
    workerEvents: block.workerEvents,
    timestamp: blockTimestamp(message, block, index),
    toolCallId: block.toolCallId,
  };
}

function toolCallToItem(call: ToolCall, index: number): TimelineToolItem {
  return {
    id: call.toolCallId || `tool:${index}:${call.timestamp}`,
    name: call.name,
    args: call.args || {},
    result: call.result,
    status: call.result?.startsWith('[ERROR]') ? 'error' : 'success',
    durationMs: call.durationMs,
    workerEvents: call.workerEvents,
    timestamp: call.timestamp || index,
    toolCallId: call.toolCallId,
  };
}

function statusForTools(tools: TimelineToolItem[]): ToolStatus {
  if (tools.some((tool) => tool.status === 'error')) return 'error';
  if (tools.some((tool) => tool.status === 'running')) return 'running';
  return 'success';
}

function isReadSearchListTool(name: string): boolean {
  const n = (name || '').toLowerCase();
  return (
    n === 'file_read' ||
    n === 'file_search' ||
    n === 'file_list' ||
    n.includes('read') ||
    n.includes('search') ||
    n.includes('grep') ||
    n.includes('list')
  );
}

function firstStringArg(args: Record<string, any>, keys: string[]): string {
  for (const key of keys) {
    const value = args?.[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}

function toolLabel(tool: TimelineToolItem): string {
  const n = tool.name.toLowerCase();
  if (n.includes('shell') || n.includes('bash') || n === 'run_command' || n.includes('terminal')) return 'Bash';
  if (n.includes('read')) return 'Read';
  if (n.includes('search') || n.includes('grep')) return 'Search';
  if (n.includes('list')) return 'List';
  if (n.includes('write') || n.includes('edit') || n.includes('patch')) return 'Edit';
  if (n.includes('browser')) return 'Browser';
  if (n.includes('web')) return 'Web';
  return tool.name;
}

function toolTarget(tool: TimelineToolItem): string {
  return firstStringArg(tool.args, ['path', 'file', 'file_path', 'query', 'url', 'command']);
}

function labelForSingleTool(tool: TimelineToolItem): string {
  const target = toolTarget(tool);
  return target ? `${toolLabel(tool)} ${target}` : toolLabel(tool);
}

function labelForGroupedTools(tools: TimelineToolItem[]): string {
  if (tools.length === 1) return labelForSingleTool(tools[0]);
  const labels = new Set(tools.map(toolLabel));
  if (labels.size === 1) {
    const label = [...labels][0];
    const noun = label === 'Search' ? 'queries' : label === 'List' ? 'directories' : 'files';
    return `${label} ${tools.length} ${noun}`;
  }
  return `Read/search ${tools.length} calls`;
}

function compactCodingToolEvents(events: TimelineEvent[]): TimelineEvent[] {
  const output: TimelineEvent[] = [];
  let group: TimelineToolEvent[] = [];

  const flush = () => {
    if (group.length === 0) return;
    const tools = group.flatMap((event) => event.tools);
    output.push({
      ...group[0],
      id: `tool-group:${tools.map((tool) => tool.id).join('|')}`,
      tools,
      label: labelForGroupedTools(tools),
      grouped: tools.length > 1,
      status: statusForTools(tools),
    });
    group = [];
  };

  for (const event of events) {
    if (
      event.kind === 'tool' &&
      event.tools.length === 1 &&
      event.status === 'success' &&
      isReadSearchListTool(event.tools[0].name)
    ) {
      group.push(event);
      continue;
    }
    flush();
    output.push(event);
  }
  flush();
  return output;
}

function compactPersonalToolEvents(events: TimelineEvent[]): TimelineEvent[] {
  const output: TimelineEvent[] = [];
  let group: TimelineToolEvent[] = [];

  const flush = () => {
    if (group.length === 0) return;
    const tools = group.flatMap((event) => event.tools);
    output.push({
      ...group[0],
      id: `tool-disclosure:${tools.map((tool) => tool.id).join('|')}`,
      tools,
      label: `Used ${tools.length} tool${tools.length === 1 ? '' : 's'}`,
      disclosure: true,
      grouped: tools.length > 1,
      status: statusForTools(tools),
    });
    group = [];
  };

  for (const event of events) {
    if (event.kind === 'tool') {
      group.push(event);
      continue;
    }
    flush();
    output.push(event);
  }
  flush();
  return output;
}

export function buildTimelineEvents({
  messages,
  toolCalls = [],
  fileEdits = [],
  runEvents = [],
  planState,
  mode,
}: BuildTimelineEventsInput): TimelineEvent[] {
  void runEvents;
  const events: TimelineEvent[] = [];
  const editToolCallIds = new Set<string>();
  const seenToolIds = new Set<string>();
  const seenEditIds = new Set<string>();
  const safeMessages = messages.filter((message): message is ChatMessage => Boolean(message));
  const safeToolCalls = filterVisibleToolCalls(
    toolCalls.filter((call): call is ToolCall => Boolean(call)),
  );
  const safeFileEdits = fileEdits.filter((edit): edit is FileEdit => Boolean(edit));

  for (const message of safeMessages) {
    for (const block of message.blocks || []) {
      if (block.type === 'file_edit' && block.edit.tool_call_id) {
        editToolCallIds.add(block.edit.tool_call_id);
      }
    }
  }
  for (const edit of safeFileEdits) {
    if (edit.tool_call_id) editToolCallIds.add(edit.tool_call_id);
  }

  safeMessages.forEach((message, messageIndex) => {
    const baseTimestamp = message.createdAt ?? messageIndex;
    if (message.role === 'user') {
      events.push({
        id: `user:${message.id}`,
        kind: 'user',
        timestamp: baseTimestamp,
        messageId: message.id,
        message,
        text: message.content,
        imageBase64: message.imageBase64,
      });
      return;
    }

    if (message.role === 'system') {
      events.push({
        id: `system:${message.id}`,
        kind: 'error',
        timestamp: baseTimestamp,
        messageId: message.id,
        text: message.content,
      });
      return;
    }

    if (message.blocks && message.blocks.length > 0) {
      message.blocks.forEach((block, blockIndex) => {
        const timestamp = blockTimestamp(message, block, blockIndex);
        const idBase = `${message.id}:${block.type}:${timestamp}:${blockIndex}`;

        switch (block.type) {
          case 'thinking':
            events.push({
              id: idBase,
              kind: 'thinking',
              timestamp,
              messageId: message.id,
              text: block.text,
              complete: block.complete,
              startedAt: block.startedAt,
              endedAt: block.endedAt,
            });
            break;
          case 'text':
            if (block.text.trim()) {
              events.push({
                id: idBase,
                kind: 'text_summary',
                timestamp,
                messageId: message.id,
                text: block.text,
                role: 'assistant',
                message,
              });
            }
            break;
          case 'knowledge_context':
            events.push({
              id: idBase,
              kind: 'knowledge',
              timestamp,
              messageId: message.id,
              sources: block.sources,
            });
            break;
          case 'tool_call': {
            if (isInternalToolName(block.name)) break;
            const item = toToolItem(block, message, blockIndex);
            const key = toolEventId(item);
            if (!item.toolCallId || !editToolCallIds.has(item.toolCallId)) {
              seenToolIds.add(key);
              events.push({
                id: `tool:${key}`,
                kind: 'tool',
                timestamp,
                messageId: message.id,
                tools: [item],
                label: labelForSingleTool(item),
                status: item.status,
              });
            }
            break;
          }
          case 'file_edit': {
            const key = editEventId(block.edit);
            seenEditIds.add(key);
            events.push({
              id: `edit:${key}`,
              kind: 'file_edit',
              timestamp,
              messageId: message.id,
              edit: block.edit,
            });
            break;
          }
          case 'image':
            events.push({
              id: idBase,
              kind: 'image',
              timestamp,
              messageId: message.id,
              base64: block.base64,
            });
            break;
          case 'plan_execution':
            events.push({
              id: idBase,
              kind: 'todo',
              timestamp,
              messageId: message.id,
              goal: block.goal || planState?.goal || '',
              todos: block.todos,
              phase: planState?.phase,
              source: 'execution',
              planExecution: block,
            });
            break;
          case 'plan_draft':
            events.push({
              id: idBase,
              kind: 'todo',
              timestamp,
              messageId: message.id,
              goal: block.goal || planState?.goal || '',
              todos: block.todos.length > 0 ? block.todos : (planState?.todos || []),
              phase: planState?.phase,
              source: 'draft',
              planDraft: block,
            });
            break;
          default:
            break;
        }
      });
      return;
    }

    if (message.reasoning) {
      events.push({
        id: `reasoning:${message.id}`,
        kind: 'thinking',
        timestamp: baseTimestamp,
        messageId: message.id,
        text: message.reasoning,
        complete: true,
      });
    }

    if (message.content.trim()) {
      events.push({
        id: `assistant:${message.id}`,
        kind: 'text_summary',
        timestamp: baseTimestamp,
        messageId: message.id,
        text: message.content,
        role: 'assistant',
        message,
      });
    } else if (message.isTool) {
      events.push({
        id: `tool-status:${message.id}`,
        kind: 'run_status',
        timestamp: baseTimestamp,
        messageId: message.id,
        event: {
          id: message.id,
          type: 'run_created',
          timestamp: baseTimestamp,
          data: {},
        },
        label: 'Working',
      });
    }
  });

  safeToolCalls.forEach((call, index) => {
    const item = toolCallToItem(call, index);
    const key = toolEventId(item);
    if (seenToolIds.has(key)) return;
    if (item.toolCallId && editToolCallIds.has(item.toolCallId)) return;
    seenToolIds.add(key);
    events.push({
      id: `tool:${key}`,
      kind: 'tool',
      timestamp: item.timestamp,
      tools: [item],
      label: labelForSingleTool(item),
      status: item.status,
    });
  });

  safeFileEdits.forEach((edit, index) => {
    const key = editEventId(edit);
    if (seenEditIds.has(key)) return;
    seenEditIds.add(key);
    events.push({
      id: `edit:${key}`,
      kind: 'file_edit',
      timestamp: edit.timestamp || index,
      edit,
    });
  });

  const projected = mode === 'personal'
    ? compactPersonalToolEvents(events)
    : compactCodingToolEvents(events);

  return projected;
}
