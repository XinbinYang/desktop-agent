import type { AgentInfo, AgentProfile, AgentType } from '../types';

export const AGENT_DEFAULT_ROLE: Record<AgentType, string> = {
  personal: 'desktop-agent',
  coding: 'code-expert',
};

export const AGENT_LABEL: Record<AgentType, string> = {
  personal: 'Personal Agent',
  coding: 'Coding Agent',
};

export type AgentProfileMap = Record<AgentType, AgentProfile>;
export type RoleDisplayNameMap = Record<string, string>;

export const DEFAULT_AGENT_PROFILES: AgentProfileMap = {
  personal: {
    agent_type: 'personal',
    display_name: 'Personal Agent',
    type_label: 'Personal Agent',
    avatar_emoji: '',
    subtitle: 'Personal AI companion',
    source: 'default',
  },
  coding: {
    agent_type: 'coding',
    display_name: 'Coding Agent',
    type_label: 'Coding Agent',
    avatar_emoji: '',
    subtitle: 'Engineering specialist',
    source: 'default',
  },
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

function cleanText(value: unknown, fallback: string): string {
  const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : '';
  return text || fallback;
}

export function normalizeAgentProfile(agentType: AgentType, raw?: Partial<AgentProfile> | null, fallbackName?: string): AgentProfile {
  const fallback = DEFAULT_AGENT_PROFILES[agentType];
  return {
    ...fallback,
    ...raw,
    agent_type: agentType,
    display_name: cleanText(raw?.display_name || fallbackName, fallback.display_name),
    type_label: cleanText(raw?.type_label, AGENT_LABEL[agentType]),
    avatar_emoji: typeof raw?.avatar_emoji === 'string' ? raw.avatar_emoji.trim() : fallback.avatar_emoji,
    subtitle: cleanText(raw?.subtitle, fallback.subtitle || ''),
  };
}

export function profilesFromAgents(agents: AgentInfo[] | undefined): AgentProfileMap {
  const profiles: AgentProfileMap = { ...DEFAULT_AGENT_PROFILES };
  for (const agent of agents || []) {
    const agentType = normalizeAgentType(agent.type);
    profiles[agentType] = normalizeAgentProfile(agentType, agent.profile, agent.name);
  }
  return profiles;
}

export function displayNameForAgent(agentType: AgentType, profiles?: Partial<Record<AgentType, AgentProfile>>): string {
  return normalizeAgentProfile(agentType, profiles?.[agentType]).display_name;
}

export function displayNameForAgentRole(
  agentType: AgentType,
  roleId?: string | null,
  profiles?: Partial<Record<AgentType, AgentProfile>>,
  roleDisplayNames?: RoleDisplayNameMap,
): string {
  const profileName = displayNameForAgent(agentType, profiles);
  if (profileName) return profileName;

  const roleName = roleId ? cleanText(roleDisplayNames?.[roleId], '') : '';
  return roleName || DEFAULT_AGENT_PROFILES[agentType].display_name;
}
