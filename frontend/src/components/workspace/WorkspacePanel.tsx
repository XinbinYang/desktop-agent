import React from 'react';
import { Code, Globe, Package } from 'lucide-react';
import {
  OpenFile,
  EditorGroup,
  ArtifactItem,
  ToolCall,
  AutomationSnapshot,
  AutomationAction,
  AutomationTrace,
  AutomationReplayStatus,
} from '../../types';
import { EditorPanel } from '../EditorPanel/EditorPanel';
import { ArtifactPanel } from '../ArtifactPanel/ArtifactPanel';
import { WorkspaceBrowser, type Annotation } from './WorkspaceBrowser';

export type WorkspaceView = 'editor' | 'preview' | 'artifacts';

interface WorkspacePanelProps {
  activeView: WorkspaceView;
  onActiveViewChange: (v: WorkspaceView) => void;
  // Editor
  editorGroups: EditorGroup[];
  activeEditorGroup: string;
  projectName: string;
  onSelectFile: (groupId: string, fileId: string) => void;
  onCloseFile: (groupId: string, fileId: string) => void;
  onMoveToGroup: (fileId: string, fromGroupId: string, toGroupId: string) => void;
  onSplitEditor: () => void;
  onCloseSplit: () => void;
  onSetActiveGroup: (groupId: string) => void;
  onFileContentChange?: (groupId: string, fileId: string, content: string) => void;
  onSaveFile?: (groupId: string, fileId: string, content: string) => void;
  // Artifacts
  artifacts: ArtifactItem[];
  isRunning: boolean;
  latestToolCall: ToolCall | null;
  automationSnapshots: AutomationSnapshot[];
  automationActions: AutomationAction[];
  automationTraces: AutomationTrace[];
  automationReplayStatus: AutomationReplayStatus | null;
  onAutomationObserve?: (source?: string) => void;
  onAutomationReplay?: (traceId: string) => void;
  // Preview
  previewUrl?: string;
  onAnnotate?: (a: Annotation) => void;
}

const VIEWS: { key: WorkspaceView; label: string; icon: React.FC<{ className?: string }> }[] = [
  { key: 'editor', label: '代码', icon: Code },
  { key: 'preview', label: '预览', icon: Globe },
  { key: 'artifacts', label: '成果', icon: Package },
];

export const WorkspacePanel: React.FC<WorkspacePanelProps> = ({
  activeView,
  onActiveViewChange,
  // Editor
  editorGroups,
  activeEditorGroup,
  projectName,
  onSelectFile,
  onCloseFile,
  onMoveToGroup,
  onSplitEditor,
  onCloseSplit,
  onSetActiveGroup,
  onFileContentChange,
  onSaveFile,
  // Artifacts
  artifacts,
  isRunning,
  latestToolCall,
  automationSnapshots,
  automationActions,
  automationTraces,
  automationReplayStatus,
  onAutomationObserve,
  onAutomationReplay,
  // Preview
  previewUrl,
  onAnnotate,
}) => {
  return (
    <div className="h-full flex flex-col bg-app">
      {/* Segmented control */}
      <div className="flex items-center border-b border-border shrink-0">
        {VIEWS.map((v) => {
          const Icon = v.icon;
          const isActive = activeView === v.key;
          return (
            <button
              key={v.key}
              onClick={() => onActiveViewChange(v.key)}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors ${
                isActive
                  ? 'bg-surface-alt text-fg border-b-2 border-accent -mb-px'
                  : 'text-fg-secondary hover:text-fg hover:bg-surface-hover'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {v.label}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeView === 'editor' && (
          <EditorPanel
            groups={editorGroups}
            activeGroupId={activeEditorGroup}
            projectName={projectName}
            onSelectFile={onSelectFile}
            onCloseFile={onCloseFile}
            onMoveToGroup={onMoveToGroup}
            onSplitEditor={onSplitEditor}
            onCloseSplit={onCloseSplit}
            onSetActiveGroup={onSetActiveGroup}
            onFileContentChange={onFileContentChange}
            onSaveFile={onSaveFile}
          />
        )}
        {activeView === 'preview' && (
          <WorkspaceBrowser url={previewUrl} onAnnotate={onAnnotate} />
        )}
        {activeView === 'artifacts' && (
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
