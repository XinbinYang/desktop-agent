import React, { useState } from 'react';
import { Brain, FileText, Zap, Activity, Moon } from 'lucide-react';
import { cn } from '../ui/cn';
import { SoulEditor } from './SoulEditor';
import { MemoryManager } from './MemoryManager';
import { HeartbeatConfig } from './HeartbeatConfig';
import { LearningsPanel } from './LearningsPanel';
import { EvolutionPanel } from './EvolutionPanel';
import { DreamsViewer } from './DreamsViewer';

export type PersonalWorkspaceTab = 'memory' | 'persona' | 'learnings' | 'heartbeat' | 'evolution' | 'dreams';

const TABS: { id: PersonalWorkspaceTab; icon: React.FC<{ className?: string }>; label: string }[] = [
  { id: 'persona', icon: FileText, label: '人格' },
  { id: 'memory', icon: Brain, label: 'Memory OS' },
  { id: 'learnings', icon: Zap, label: '学习' },
  { id: 'heartbeat', icon: Activity, label: '心跳' },
  { id: 'dreams', icon: Moon, label: '梦境' },
  { id: 'evolution', icon: Zap, label: '进化' },
];

interface PersonalWorkspacePanelProps {
  className?: string;
  activeTabHint?: PersonalWorkspaceTab;
  focusSignal?: number;
}

export const PersonalWorkspacePanel: React.FC<PersonalWorkspacePanelProps> = ({
  className,
  activeTabHint,
  focusSignal = 0,
}) => {
  const [activeTab, setActiveTab] = useState<PersonalWorkspaceTab>(activeTabHint || 'persona');

  React.useEffect(() => {
    if (activeTabHint) setActiveTab(activeTabHint);
  }, [activeTabHint, focusSignal]);

  return (
    <div className={cn('flex flex-col h-full min-h-0', className)}>
      <div className="flex border-b border-border shrink-0 overflow-x-auto">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              'flex items-center gap-1 shrink-0 px-2.5 py-1.5 text-[11px] font-medium transition-colors border-b-2 -mb-px',
              activeTab === tab.id
                ? 'border-accent text-fg'
                : 'border-transparent text-fg-muted hover:text-fg-secondary'
            )}
          >
            <tab.icon className="w-3 h-3" />
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === 'persona' && <SoulEditor />}
        {activeTab === 'memory' && <MemoryManager focusSignal={focusSignal} />}
        {activeTab === 'learnings' && <LearningsPanel />}
        {activeTab === 'heartbeat' && <HeartbeatConfig />}
        {activeTab === 'dreams' && <DreamsViewer />}
        {activeTab === 'evolution' && <EvolutionPanel />}
      </div>
    </div>
  );
};
