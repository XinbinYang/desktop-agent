import type { AgentInfo, AgentProfile, AgentType } from '../types';

export const AGENT_DEFAULT_ROLE: Record<string, string> = {
  personal: 'desktop-agent',
  coding: 'code-expert',
};

export const AGENT_LABEL: Record<string, string> = {
  personal: 'Personal Agent',
  coding: 'Coding Agent',
};

export type AgentProfileMap = Record<string, AgentProfile> & {
  personal: AgentProfile;
  coding: AgentProfile;
};
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
  return value === 'personal' || value === 'coding' || (typeof value === 'string' && /^specialist:[a-z0-9][a-z0-9-]*$/.test(value));
}

export function roleForAgent(agentType: AgentType): string {
  return agentType === 'coding' ? 'code-expert' : 'desktop-agent';
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

function defaultProfileForAgent(agentType: AgentType): AgentProfile {
  if (agentType === 'personal' || agentType === 'coding') {
    return DEFAULT_AGENT_PROFILES[agentType];
  }
  const slug = agentType.replace(/^specialist:/, '');
  const display = slug
    .split('-')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ') || 'Specialist Agent';
  return {
    agent_type: agentType,
    display_name: display,
    type_label: 'Specialist Agent',
    avatar_emoji: '',
    subtitle: 'User-created specialist',
    source: 'default',
  };
}

export function normalizeAgentProfile(agentType: AgentType, raw?: Partial<AgentProfile> | null, fallbackName?: string): AgentProfile {
  const fallback = defaultProfileForAgent(agentType);
  return {
    ...fallback,
    ...raw,
    agent_type: agentType,
    display_name: cleanText(raw?.display_name || fallbackName, fallback.display_name),
    type_label: cleanText(raw?.type_label, AGENT_LABEL[agentType] || fallback.type_label),
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
