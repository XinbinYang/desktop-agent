import { describe, expect, it } from 'vitest';
import { buildPersonalConversation } from '../../lib/personalConversation';
import type { ChatMessage, PlanState, ToolCall } from '../../types';

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
  pending_clarification: false,
};

describe('buildPersonalConversation', () => {
  it('groups adjacent messages by author and keeps user and assistant separate', () => {
    const messages: ChatMessage[] = [
      { id: 'u1', role: 'user', content: 'hello', isTool: false, createdAt: 1000 },
      { id: 'u2', role: 'user', content: 'one more thing', isTool: false, createdAt: 2000 },
      { id: 'a1', role: 'assistant', content: 'hi there', isTool: false, createdAt: 3000, turnComplete: true },
    ];

    const groups = buildPersonalConversation({ messages, planState: idlePlanState });

    expect(groups).toHaveLength(2);
    expect(groups[0].role).toBe('user');
    expect(groups[0].items.map((item) => item.text)).toEqual(['hello', 'one more thing']);
    expect(groups[1].role).toBe('assistant');
  });

  it('uses a custom Personal Agent display name for assistant messages', () => {
    const messages: ChatMessage[] = [
      { id: 'a1', role: 'assistant', content: 'hi there', isTool: false, createdAt: 3000, turnComplete: true },
    ];

    const groups = buildPersonalConversation({
      messages,
      planState: idlePlanState,
      assistantDisplayName: '镜与刃',
    });

    expect(groups[0].authorName).toBe('镜与刃');
    expect(groups[0].items[0].authorName).toBe('镜与刃');
  });

  it('folds assistant reasoning, tools, knowledge, and text into one social message item', () => {
    const messages: ChatMessage[] = [{
      id: 'a1',
      role: 'assistant',
      content: '',
      isTool: false,
      createdAt: 1000,
      turnComplete: true,
      blocks: [
        { type: 'thinking', text: 'checking memory', timestamp: 1001, complete: true },
        { type: 'knowledge_context', sources: [{ source_path: 'memory.md', score: 0.9, preview: 'favorite tea' }], timestamp: 1002 },
        { type: 'tool_call', name: 'knowledge_search', args: { query: 'tea' }, result: 'match', status: 'success', toolCallId: 't1', timestamp: 1003 },
        { type: 'text', text: 'You like jasmine tea.', timestamp: 1004 },
      ],
    }];

    const groups = buildPersonalConversation({ messages, planState: idlePlanState });
    const item = groups[0].items[0];

    expect(item.text).toBe('You like jasmine tea.');
    expect(item.activities.map((activity) => activity.kind)).toEqual(['thinking', 'knowledge', 'tool']);
    expect(item.activities.find((activity) => activity.kind === 'tool')?.label).toContain('Used');
  });

  it('marks live assistant text as streaming so the surface can render it as plain text', () => {
    const messages: ChatMessage[] = [{
      id: 'a1',
      role: 'assistant',
      content: '',
      isTool: false,
      turnComplete: false,
      blocks: [{ type: 'text', text: '**still streaming**', timestamp: 1 }],
    }];

    const groups = buildPersonalConversation({ messages, planState: idlePlanState });

    expect(groups[0].items[0].isStreaming).toBe(true);
    expect(groups[0].items[0].text).toBe('**still streaming**');
  });

  it('keeps input message order even when newer local messages lack timestamps', () => {
    const messages: ChatMessage[] = [
      {
        id: 'a-history',
        role: 'assistant',
        content: 'older server answer',
        isTool: false,
        createdAt: Date.UTC(2026, 4, 20, 8, 0, 0),
        turnComplete: true,
      },
      {
        id: 'u-local',
        role: 'user',
        content: 'new local question',
        isTool: false,
      },
    ];

    const groups = buildPersonalConversation({ messages, planState: idlePlanState });

    expect(groups.map((group) => group.items[0].text)).toEqual([
      'older server answer',
      'new local question',
    ]);
  });

  it('leaves timestamp-less messages without display time metadata', () => {
    const messages: ChatMessage[] = [
      { id: 'u1', role: 'user', content: 'hello without a clock', isTool: false },
    ];

    const groups = buildPersonalConversation({ messages, planState: idlePlanState });

    expect(groups[0].startedAt).toBeUndefined();
    expect(groups[0].items[0].createdAt).toBeUndefined();
  });

  it('uses fallback tool timestamps instead of tool durations', () => {
    const toolTimestamp = Date.UTC(2026, 4, 20, 9, 30, 0);
    const toolCalls: ToolCall[] = [{
      name: 'knowledge_search',
      args: { query: 'market' },
      result: 'ok',
      timestamp: toolTimestamp,
      durationMs: 12,
      toolCallId: 'tool-1',
    }];

    const groups = buildPersonalConversation({ messages: [], toolCalls, planState: idlePlanState });
    const item = groups[0].items[0];
    const activity = item.activities[0];

    expect(item.createdAt).toBe(toolTimestamp);
    expect(activity.timestamp).toBe(toolTimestamp);
  });
});
