import React from 'react';
import {
  Sparkles,
  FolderOpen,
  MessageSquare,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  User,
  Code,
  type LucideIcon,
} from 'lucide-react';
import { type SidebarSection, type AgentType } from '../types';
import { cn } from './ui/cn';
import { Tooltip } from './ui/Tooltip';

interface ActivityBarProps {
  activeSection: SidebarSection;
  activeAgent: AgentType;
  sidebarCollapsed: boolean;
  onSectionChange: (section: SidebarSection) => void;
  onAgentChange: (agent: AgentType) => void;
  onToggleSidebar: () => void;
}

interface ActivityItem {
  id: SidebarSection | AgentType;
  icon: LucideIcon;
  label: string;
  isAgent?: boolean;
}

const AGENT_ITEMS: ActivityItem[] = [
  { id: 'personal', icon: User, label: 'Personal', isAgent: true },
  { id: 'coding', icon: Code, label: 'Coding', isAgent: true },
];

const SECTION_ITEMS: ActivityItem[] = [
  { id: 'skills', icon: Sparkles, label: 'Skills' },
  { id: 'project', icon: FolderOpen, label: 'Project' },
  { id: 'sessions', icon: MessageSquare, label: 'Sessions' },
  { id: 'settings', icon: Settings, label: 'Settings' },
];

export const ActivityBar: React.FC<ActivityBarProps> = ({
  activeSection,
  activeAgent,
  sidebarCollapsed,
  onSectionChange,
  onAgentChange,
  onToggleSidebar,
}) => {
  const handleAgentClick = (agentType: AgentType) => {
    if (!sidebarCollapsed && activeAgent === agentType) {
      onToggleSidebar();
    } else if (sidebarCollapsed) {
      onAgentChange(agentType);
      onToggleSidebar();
    } else {
      onAgentChange(agentType);
      // Auto-switch section: personal → personal, coding → project
      onSectionChange(agentType === 'personal' ? 'personal' : 'project');
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
        {AGENT_ITEMS.map((item) => {
          const isActive = activeAgent === item.id;
          return (
            <Tooltip key={item.id} content={<span className="text-[11px]">{item.label} Agent</span>} side="right">
              <button
                type="button"
                onClick={() => handleAgentClick(item.id as AgentType)}
                className={cn(
                  'relative w-10 h-10 rounded-full flex items-center justify-center transition-all',
                  isActive
                    ? item.id === 'personal'
                      ? 'bg-accent/10 text-accent ring-1 ring-accent/30'
                      : 'bg-success/10 text-success ring-1 ring-success/30'
                    : 'text-fg-secondary hover:text-fg hover:bg-surface-hover'
                )}
                aria-label={`${item.label} Agent`}
              >
                <item.icon className="w-5 h-5" />
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
