import React from 'react';
import { cn } from './cn';

interface Tab {
  id: string;
  label: string;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (id: string) => void;
  className?: string;
}

export const Tabs: React.FC<TabsProps> = ({
  tabs,
  activeTab,
  onTabChange,
  className,
}) => {
  return (
    <div className={cn('flex border-b border-border', className)}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onTabChange(tab.id)}
          className={cn(
            'flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors',
            activeTab === tab.id
              ? 'bg-surface text-fg'
              : 'text-fg-muted hover:text-fg-secondary'
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
};
