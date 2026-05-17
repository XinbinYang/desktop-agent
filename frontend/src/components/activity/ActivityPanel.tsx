import React, { useState } from 'react';
import {
  Wrench, FileDiff, Play, TestTube, AlertTriangle, BarChart3,
  ChevronDown, ChevronRight,
} from 'lucide-react';
import type { ToolCall, FileEdit, RunEvent } from '../../types';
import { ToolCallView } from '../ToolCallView';
import { ChangesPanel } from '../ChangesPanel';
import { RunSummaryPanel } from '../RunSummaryPanel';
import { TestsPanel } from '../TestsPanel';
import { ProblemsPanel } from '../ProblemsPanel';
import { EvalPanel } from '../EvalPanel';

interface ActivityPanelProps {
  toolCalls: ToolCall[];
  fileEdits: FileEdit[];
  runEvents: RunEvent[];
  // ChangesPanel
  onOpenFileFromChanges: (path: string) => void;
  // TestsPanel
  onOpenFileFromTests: (path: string) => void;
  // ProblemsPanel
  onOpenFileFromProblems: (path: string, line?: number) => void;
  // Runs
  onOpenWorktree: (runId: string) => void;
  onApplyRun: (runId: string) => void;
  onMergeRun: (runId: string) => void;
  onDiscardRun: (runId: string) => void;
}

type ActivitySection = 'tools' | 'changes' | 'runs' | 'tests' | 'problems' | 'eval';

const SECTIONS: { key: ActivitySection; label: string; icon: React.FC<{ className?: string }> }[] = [
  { key: 'tools', label: '工具', icon: Wrench },
  { key: 'changes', label: '变更', icon: FileDiff },
  { key: 'runs', label: '运行', icon: Play },
  { key: 'tests', label: '测试', icon: TestTube },
  { key: 'problems', label: '问题', icon: AlertTriangle },
  { key: 'eval', label: '评估', icon: BarChart3 },
];

export const ActivityPanel: React.FC<ActivityPanelProps> = ({
  toolCalls,
  fileEdits,
  runEvents,
  onOpenFileFromChanges,
  onOpenFileFromTests,
  onOpenFileFromProblems,
  onOpenWorktree,
  onApplyRun,
  onMergeRun,
  onDiscardRun,
}) => {
  const [expanded, setExpanded] = useState<Set<ActivitySection>>(new Set(['tools', 'changes']));

  const toggle = (s: ActivitySection) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s); else next.add(s);
      return next;
    });
  };

  return (
    <div className="h-full flex flex-col bg-app overflow-y-auto">
      {SECTIONS.map(({ key, label, icon: Icon }) => {
        const isOpen = expanded.has(key);
        return (
          <div key={key} className="border-b border-border last:border-b-0">
            <button
              onClick={() => toggle(key)}
              className="flex items-center gap-1.5 w-full px-3 py-2 text-xs font-medium text-fg-secondary hover:text-fg hover:bg-surface-hover transition-colors"
            >
              {isOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              <Icon className="w-3.5 h-3.5" />
              {label}
              {/* Summary chips */}
              {key === 'tools' && toolCalls.length > 0 && (
                <span className="ml-auto text-[10px] text-fg-muted bg-surface-alt px-1.5 py-0.5 rounded">
                  {toolCalls.length}
                </span>
              )}
              {key === 'changes' && fileEdits.length > 0 && (
                <span className="ml-auto text-[10px] text-fg-muted bg-surface-alt px-1.5 py-0.5 rounded">
                  {fileEdits.length}
                </span>
              )}
              {key === 'runs' && runEvents.length > 0 && (
                <span className="ml-auto text-[10px] text-fg-muted bg-surface-alt px-1.5 py-0.5 rounded">
                  {runEvents.length}
                </span>
              )}
            </button>

            {isOpen && (
              <div className="px-1 pb-2">
                {key === 'tools' && (
                  toolCalls.length === 0 ? (
                    <div className="text-xs text-fg-muted text-center py-4">暂无工具调用</div>
                  ) : (
                    toolCalls.map((tc, i) => (
                      <ToolCallView
                        key={`${tc.timestamp}-${i}`}
                        name={tc.name}
                        args={tc.args}
                        result={tc.result}
                        status={tc.result.startsWith('[ERROR]') ? 'error' : 'success'}
                        durationMs={tc.durationMs}
                        workerEvents={tc.workerEvents}
                      />
                    ))
                  )
                )}
                {key === 'changes' && (
                  <ChangesPanel edits={fileEdits} onOpenFile={onOpenFileFromChanges} />
                )}
                {key === 'runs' && (
                  <RunSummaryPanel
                    events={runEvents}
                    onOpenWorktree={onOpenWorktree}
                    onApplyRun={onApplyRun}
                    onMergeRun={onMergeRun}
                    onDiscardRun={onDiscardRun}
                  />
                )}
                {key === 'tests' && <TestsPanel onOpenFile={onOpenFileFromTests} />}
                {key === 'problems' && <ProblemsPanel onOpenFile={onOpenFileFromProblems} />}
                {key === 'eval' && <EvalPanel />}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
