import React, { useState } from 'react';
import { Brain, FileText, Zap, Activity, Moon, Bot } from 'lucide-react';
import { cn } from '../ui/cn';
import type { AgentProfile, ArtifactItem, AutomationAction, AutomationReplayStatus, AutomationSnapshot, AutomationTrace, ToolCall } from '../../types';
import { ArtifactPanel } from '../ArtifactPanel/ArtifactPanel';
import { SoulEditor } from './SoulEditor';
import { MemoryManager } from './MemoryManager';
import { HeartbeatConfig } from './HeartbeatConfig';
import { LearningsPanel } from './LearningsPanel';
import { EvolutionPanel } from './EvolutionPanel';
import { DreamsViewer } from './DreamsViewer';

export type PersonalWorkspaceTab = 'memory' | 'persona' | 'learnings' | 'heartbeat' | 'evolution' | 'dreams' | 'automation';

const TABS: { id: PersonalWorkspaceTab; icon: React.FC<{ className?: string }>; label: string }[] = [
  { id: 'persona', icon: FileText, label: '身份与偏好' },
  { id: 'memory', icon: Brain, label: '记忆' },
  { id: 'learnings', icon: Zap, label: '学习记录' },
  { id: 'heartbeat', icon: Activity, label: '自动维护' },
  { id: 'dreams', icon: Moon, label: '记忆整理' },
  { id: 'evolution', icon: Zap, label: '能力进化' },
  { id: 'automation', icon: Bot, label: '自动化' },
];

interface PersonalWorkspacePanelProps {
  className?: string;
  profile?: AgentProfile;
  onProfileChanged?: (profile: AgentProfile) => void;
  activeTabHint?: PersonalWorkspaceTab;
  focusSignal?: number;
  artifacts?: ArtifactItem[];
  isRunning?: boolean;
  latestToolCall?: ToolCall | null;
  automationSnapshots?: AutomationSnapshot[];
  automationActions?: AutomationAction[];
  automationTraces?: AutomationTrace[];
  automationReplayStatus?: AutomationReplayStatus | null;
  onAutomationObserve?: (source?: string) => void;
  onAutomationReplay?: (traceId: string) => void;
}

export const PersonalWorkspacePanel: React.FC<PersonalWorkspacePanelProps> = ({
  className,
  profile,
  onProfileChanged,
  activeTabHint,
  focusSignal = 0,
  artifacts = [],
  isRunning = false,
  latestToolCall = null,
  automationSnapshots = [],
  automationActions = [],
  automationTraces = [],
  automationReplayStatus = null,
  onAutomationObserve,
  onAutomationReplay,
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
        {activeTab === 'persona' && <SoulEditor profile={profile} onProfileChanged={onProfileChanged} />}
        {activeTab === 'memory' && <MemoryManager focusSignal={focusSignal} />}
        {activeTab === 'learnings' && <LearningsPanel />}
        {activeTab === 'heartbeat' && <HeartbeatConfig />}
        {activeTab === 'dreams' && <DreamsViewer />}
        {activeTab === 'evolution' && <EvolutionPanel />}
        {activeTab === 'automation' && (
          <ArtifactPanel
            artifacts={artifacts}
            isRunning={isRunning}
            latestToolCall={latestToolCall}
            automationSnapshots={automationSnapshots}
            automationActions={automationActions}
            automationTraces={automationTraces}
            automationReplayStatus={automationReplayStatus}
            onAutomationObserve={onAutomationObserve}
            onAutomationReplay={onAutomationReplay}
          />
        )}
      </div>
    </div>
  );
};
