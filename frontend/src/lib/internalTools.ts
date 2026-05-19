import type { AssistantBlock, ToolCall } from '../types';

const INTERNAL_TOOL_NAMES = new Set([
  'plan_ask_questions',
  'plan_write_draft',
  'plan_update_todos',
]);

export function isInternalToolName(name?: string | null): boolean {
  return INTERNAL_TOOL_NAMES.has((name || '').toLowerCase());
}

export function filterVisibleToolCalls(toolCalls: ToolCall[] = []): ToolCall[] {
  return toolCalls.filter((call) => !isInternalToolName(call.name));
}

export function filterVisibleAssistantBlocks(blocks: AssistantBlock[] = []): AssistantBlock[] {
  return blocks.filter((block) => block.type !== 'tool_call' || !isInternalToolName(block.name));
}
