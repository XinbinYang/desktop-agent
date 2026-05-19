import { describe, expect, it } from 'vitest';
import { buildTimelineEvents } from '../../lib/timelineEvents';
import type { ChatMessage, FileEdit, PlanState } from '../../types';

const idlePlanState: PlanState = {
  mode: 'agent',
  phase: 'idle',
  goal: '',
  draft: '',
  structured_plan: null,
  questions: [],
  todos: [],
  decisions: {},
  approved: false,
};

describe('timelineEvents', () => {
  it('projects assistant thinking, text, and tool blocks into event order', () => {
    const messages: ChatMessage[] = [{
      id: 'a1',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [
        { type: 'thinking', text: 'checking files', timestamp: 1, complete: true },
        { type: 'tool_call', name: 'file_read', args: { path: 'src/App.tsx' }, result: 'ok', status: 'success', toolCallId: 'tc1', timestamp: 2 },
        { type: 'text', text: 'Done', timestamp: 3 },
      ],
    }];

    const events = buildTimelineEvents({ messages, planState: idlePlanState, mode: 'coding' });

    expect(events.map((event) => event.kind)).toEqual(['thinking', 'tool', 'text_summary']);
    expect(events[1]).toMatchObject({ kind: 'tool', label: 'Read src/App.tsx' });
  });

  it('dedupes file edits against matching tool calls by tool_call_id', () => {
    const edit: FileEdit = {
      path: 'src/example.ts',
      operation: 'modify',
      old_text: 'old',
      new_text: 'new',
      unified_diff: '-old\n+new\n',
      stats: { added: 1, removed: 1 },
      truncated: false,
      tool_call_id: 'tc-edit',
      timestamp: 2,
    };
    const messages: ChatMessage[] = [{
      id: 'a1',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [
        { type: 'tool_call', name: 'file_write', args: { path: edit.path }, result: 'updated', status: 'success', toolCallId: 'tc-edit', timestamp: 1 },
        { type: 'file_edit', edit, timestamp: 2 },
      ],
    }];

    const events = buildTimelineEvents({ messages, fileEdits: [edit], planState: idlePlanState, mode: 'coding' });

    expect(events.map((event) => event.kind)).toEqual(['file_edit']);
  });

  it('groups consecutive read/search/list calls in coding mode', () => {
    const messages: ChatMessage[] = [{
      id: 'a1',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [
        { type: 'tool_call', name: 'file_read', args: { path: 'a.ts' }, result: 'a', status: 'success', toolCallId: 'r1', timestamp: 1 },
        { type: 'tool_call', name: 'file_read', args: { path: 'b.ts' }, result: 'b', status: 'success', toolCallId: 'r2', timestamp: 2 },
        { type: 'tool_call', name: 'file_read', args: { path: 'c.ts' }, result: 'c', status: 'success', toolCallId: 'r3', timestamp: 3 },
      ],
    }];

    const events = buildTimelineEvents({ messages, planState: idlePlanState, mode: 'coding' });
    const toolEvent = events[0];

    expect(events).toHaveLength(1);
    expect(toolEvent).toMatchObject({ kind: 'tool', label: 'Read 3 files', grouped: true });
  });

  it('omits internal plan tools from message blocks and global tool calls', () => {
    const messages: ChatMessage[] = [{
      id: 'a1',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [
        { type: 'tool_call', name: 'plan_ask_questions', args: {}, result: 'ok', status: 'success', toolCallId: 'p1', timestamp: 1 },
        { type: 'tool_call', name: 'plan_write_draft', args: {}, result: 'ok', status: 'success', toolCallId: 'p2', timestamp: 2 },
        { type: 'tool_call', name: 'plan_update_todos', args: {}, result: 'ok', status: 'success', toolCallId: 'p3', timestamp: 3 },
        { type: 'tool_call', name: 'file_read', args: { path: 'a.ts' }, result: 'a', status: 'success', toolCallId: 'r1', timestamp: 4 },
      ],
    }];

    const events = buildTimelineEvents({
      messages,
      toolCalls: [
        { name: 'plan_write_draft', args: {}, result: 'ok', timestamp: 5, toolCallId: 'p4' },
        { name: 'file_search', args: { query: 'x' }, result: 'x', timestamp: 6, toolCallId: 's1' },
      ],
      planState: idlePlanState,
      mode: 'coding',
    });

    expect(JSON.stringify(events)).not.toContain('plan_');
    expect(events.filter((event) => event.kind === 'tool')).toHaveLength(1);
    expect(events[0]).toMatchObject({ kind: 'tool', label: 'Read/search 2 calls', grouped: true });
  });

  it('collapses adjacent personal tool calls into a disclosure', () => {
    const messages: ChatMessage[] = [{
      id: 'a1',
      role: 'assistant',
      content: '',
      isTool: false,
      blocks: [
        { type: 'tool_call', name: 'knowledge_search', args: { query: 'memory' }, result: 'one', status: 'success', toolCallId: 'k1', timestamp: 1 },
        { type: 'tool_call', name: 'file_read', args: { path: 'notes.md' }, result: 'two', status: 'success', toolCallId: 'k2', timestamp: 2 },
      ],
    }];

    const events = buildTimelineEvents({ messages, planState: idlePlanState, mode: 'personal' });

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ kind: 'tool', label: 'Used 2 tools', disclosure: true });
  });

  it('does not project backend run lifecycle events into the main timeline', () => {
    const messages: ChatMessage[] = [{
      id: 'a1',
      role: 'assistant',
      content: 'Ready.',
      isTool: false,
      createdAt: 1,
    }];

    const events = buildTimelineEvents({
      messages,
      planState: idlePlanState,
      mode: 'coding',
      runEvents: [
        { id: 'r1', type: 'run_created', timestamp: 2, data: {} },
        { id: 'r2', type: 'context_pack', timestamp: 3, data: {} },
        { id: 'r3', type: 'skills_matched', timestamp: 4, data: { skills: [{ id: 's1' }] } },
        { id: 'r4', type: 'run_completed', timestamp: 5, data: { summary: 'Run completed after 1 iteration(s).' } },
      ],
    });

    expect(events.map((event) => event.kind)).toEqual(['text_summary']);
    expect(JSON.stringify(events)).not.toContain('run_created');
    expect(JSON.stringify(events)).not.toContain('skills_matched');
  });
});
