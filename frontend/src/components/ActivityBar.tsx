import React from 'react';
import {
  Sparkles,
  LayoutPanelLeft,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  User,
  Code,
  Bot,
  Loader2,
  type LucideIcon,
} from 'lucide-react';
import { type SidebarSection, type AgentType } from '../types';
import { cn } from './ui/cn';
import { Tooltip } from './ui/Tooltip';
import { displayNameForAgent, type AgentProfileMap } from '../lib/agentProfiles';

interface ActivityBarProps {
  activeSection: SidebarSection;
  activeAgent: AgentType;
  agentProfiles?: AgentProfileMap;
  sidebarCollapsed: boolean;
  onSectionChange: (section: SidebarSection) => void;
  onAgentChange: (agent: AgentType) => void;
  onToggleSidebar: () => void;
  personalRunning?: boolean;
  codingRunning?: boolean;
  agentRunning?: Partial<Record<AgentType, boolean>>;
}

interface ActivityItem {
  id: SidebarSection | AgentType;
  icon: LucideIcon;
  label: string;
  isAgent?: boolean;
}

const SECTION_ITEMS: ActivityItem[] = [
  { id: 'skills', icon: Sparkles, label: 'Skills' },
  { id: 'workspace', icon: LayoutPanelLeft, label: 'Workspace' },
  { id: 'settings', icon: Settings, label: 'Settings' },
];

export const ActivityBar: React.FC<ActivityBarProps> = ({
  activeSection,
  activeAgent,
  agentProfiles,
  sidebarCollapsed,
  onSectionChange,
  onAgentChange,
  onToggleSidebar,
  personalRunning = false,
  codingRunning = false,
  agentRunning,
}) => {
  const runningByAgent: Partial<Record<AgentType, boolean>> = {
    personal: personalRunning,
    coding: codingRunning,
    ...(agentRunning || {}),
  };

  const agentItems = React.useMemo<ActivityItem[]>(() => {
    const profiles = agentProfiles || {};
    const builtins: ActivityItem[] = [
      { id: 'personal', icon: User, label: displayNameForAgent('personal', profiles), isAgent: true },
      { id: 'coding', icon: Code, label: displayNameForAgent('coding', profiles), isAgent: true },
    ];
    const specialists = Object.values(profiles)
      .filter((profile) => profile.agent_type.startsWith('specialist:'))
      .sort((a, b) => a.display_name.localeCompare(b.display_name))
      .map<ActivityItem>((profile) => ({
        id: profile.agent_type,
        icon: Bot,
        label: profile.display_name,
        isAgent: true,
      }));
    return [...builtins, ...specialists];
  }, [agentProfiles]);

  const handleAgentClick = (agentType: AgentType) => {
    if (!sidebarCollapsed && activeAgent === agentType) {
      onToggleSidebar();
    } else if (sidebarCollapsed) {
      onAgentChange(agentType);
      onToggleSidebar();
    } else {
      onAgentChange(agentType);
      // Auto-switch section: personal → personal, coding → workspace
      onSectionChange(agentType === 'personal' ? 'personal' : 'workspace');
    }
  };

  const handleItemClick = (section: SidebarSection) => {
    if (!sidebarCollapsed && activeSection === section) {
      onToggleSidebar();
    } else if (sidebarCollapsed) {
      onSectionChange(section);
      onToggleSidebar();
    } else {
      onSectionChange(section);
    }
  };

  return (
    <div className="w-12 bg-surface border-r border-border flex flex-col items-center py-2 flex-shrink-0 select-none">
      {/* Agent entries — top */}
      <div className="flex flex-col items-center gap-1 mb-2">
        {agentItems.map((item) => {
          const isActive = activeAgent === item.id;
          const agentName = displayNameForAgent(item.id as AgentType, agentProfiles);
          const isPersonal = item.id === 'personal';
          const isCoding = item.id === 'coding';
          return (
            <Tooltip key={item.id} content={<span className="text-[11px]">{agentName}</span>} side="right">
              <button
                type="button"
                onClick={() => handleAgentClick(item.id as AgentType)}
                className={cn(
                  'relative w-10 h-10 rounded-full flex items-center justify-center transition-all',
                  isActive
                    ? isPersonal
                      ? 'bg-accent/10 text-accent ring-1 ring-accent/30'
                      : isCoding
                        ? 'bg-success/10 text-success ring-1 ring-success/30'
                        : 'bg-warning/10 text-warning ring-1 ring-warning/30'
                    : 'text-fg-secondary hover:text-fg hover:bg-surface-hover'
                )}
                aria-label={agentName}
              >
                <item.icon className="w-5 h-5" />
                {runningByAgent[item.id as AgentType] && (
                  <Loader2
                    className="absolute -top-0.5 -right-0.5 w-3 h-3 animate-spin text-success"
                    aria-label={`${agentName} running`}
                  />
                )}
              </button>
            </Tooltip>
          );
        })}
      </div>

      {/* Divider */}
      <div className="w-8 h-px bg-border my-1" />

      {/* Section icons */}
      <div className="flex-1 flex flex-col items-center gap-1">
        {SECTION_ITEMS.map((item) => {
          const isActive = !sidebarCollapsed && activeSection === item.id;
          return (
            <Tooltip key={item.id} content={<span className="text-[11px]">{item.label}</span>} side="right">
              <button
                type="button"
                onClick={() => handleItemClick(item.id as SidebarSection)}
                className={cn(
                  'relative w-12 h-12 flex items-center justify-center transition-colors',
                  isActive
                    ? 'bg-accent/10 text-accent'
                    : 'text-fg-secondary hover:text-fg hover:bg-surface-hover'
                )}
                aria-label={item.label}
              >
                {isActive && (
                  <span className="absolute left-0 top-1 bottom-1 w-0.5 bg-accent rounded-r-full" />
                )}
                <item.icon className="w-5 h-5" />
              </button>
            </Tooltip>
          );
        })}
      </div>

      {/* Bottom: collapse/expand sidebar */}
      <Tooltip content={<span className="text-[11px]">{sidebarCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'} (Ctrl+B)</span>} side="right">
        <button
          type="button"
          onClick={onToggleSidebar}
          className="w-12 h-12 flex items-center justify-center text-fg-secondary hover:text-fg transition-colors"
          aria-label={sidebarCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
        >
          {sidebarCollapsed ? (
            <PanelLeftOpen className="w-5 h-5" />
          ) : (
            <PanelLeftClose className="w-5 h-5" />
          )}
        </button>
      </Tooltip>
    </div>
  );
};
