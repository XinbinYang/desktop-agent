import type { AgentType } from '../types';

export const AGENT_DEFAULT_ROLE: Record<AgentType, string> = {
  personal: 'desktop-agent',
  coding: 'code-expert',
};

export const AGENT_LABEL: Record<AgentType, string> = {
  personal: 'Personal Agent',
  coding: 'Coding Agent',
};

export function isAgentType(value: unknown): value is AgentType {
  return value === 'personal' || value === 'coding';
}

export function roleForAgent(agentType: AgentType): string {
  return AGENT_DEFAULT_ROLE[agentType];
}

export function agentForRole(roleId?: string): AgentType {
  return roleId === 'code-expert' ? 'coding' : 'personal';
}

export function normalizeAgentType(value: unknown, roleId?: string): AgentType {
  return isAgentType(value) ? value : agentForRole(roleId);
}
