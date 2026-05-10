import React from 'react';
import {
  Zap,
  FolderOpen,
  MessageSquare,
  BookOpen,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  type LucideIcon,
} from 'lucide-react';
import { type SidebarSection } from '../types';
import { cn } from './ui/cn';
import { Tooltip } from './ui/Tooltip';

interface ActivityBarProps {
  activeSection: SidebarSection;
  sidebarCollapsed: boolean;
  onSectionChange: (section: SidebarSection) => void;
  onToggleSidebar: () => void;
}

interface ActivityItem {
  id: SidebarSection;
  icon: LucideIcon;
  label: string;
}

const ACTIVITY_ITEMS: ActivityItem[] = [
  { id: 'tools', icon: Zap, label: 'Tools' },
  { id: 'project', icon: FolderOpen, label: 'Project' },
  { id: 'sessions', icon: MessageSquare, label: 'Sessions' },
  { id: 'knowledge', icon: BookOpen, label: 'Knowledge' },
  { id: 'settings', icon: Settings, label: 'Settings' },
];

export const ActivityBar: React.FC<ActivityBarProps> = ({
  activeSection,
  sidebarCollapsed,
  onSectionChange,
  onToggleSidebar,
}) => {
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
      {/* Section icons */}
      <div className="flex-1 flex flex-col items-center gap-1">
        {ACTIVITY_ITEMS.map((item) => {
          const isActive = !sidebarCollapsed && activeSection === item.id;
          return (
            <Tooltip key={item.id} content={<span className="text-[11px]">{item.label}</span>} side="right">
              <button
                type="button"
                onClick={() => handleItemClick(item.id)}
                className={cn(
                  'relative w-12 h-12 flex items-center justify-center transition-colors',
                  isActive
                    ? 'text-white'
                    : 'text-fg-secondary hover:text-fg'
                )}
                aria-label={item.label}
              >
                {/* Active indicator bar — left edge, only when sidebar is open */}
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
