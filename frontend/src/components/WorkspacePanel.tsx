import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Panel, Group, Separator } from 'react-resizable-panels';
import { Plus, Archive, RotateCcw, FolderOpen } from 'lucide-react';
import type { ProjectInfo, FileNode, SessionHistoryItem, SessionHistoryResponse } from '../types';
import { ProjectPanel } from './ProjectPanel';
import type { FileTreeAction } from './FileTree';
import { SessionHistoryPanel, type ProjectHistoryAction } from './SessionHistoryPanel';
import type { AgentProfileMap } from '../lib/agentProfiles';

const LAYOUT_KEY = 'desktop-agent-workspace-split';
const DEFAULT_LAYOUT: Record<string, number> = { 'ws-sessions': 58, 'ws-files': 42 };

function loadLayout(): Record<string, number> {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed['ws-sessions'] === 'number' && typeof parsed['ws-files'] === 'number') {
        return parsed;
      }
    }
  } catch { /* ignore */ }
  return DEFAULT_LAYOUT;
}

interface WorkspacePanelProps {
  // Top zone — projects & sessions
  sessionHistory?: SessionHistoryResponse | null;
  sessions?: SessionHistoryItem[];
  agentProfiles?: AgentProfileMap;
  currentSession?: string;
  currentProjectPath?: string | null;
  onNewSession?: () => void;
  onCompactSession?: () => void;
  onRewindSession?: () => void;
  onSwitchSession?: (id: string, projectPath?: string | null) => void;
  onArchiveSession?: (id: string) => void;
  onDeleteSession?: (id: string) => void;
  onOpenProject?: (path: string) => void;
  onOpenProjectModal?: () => void;
  onProjectAction?: (action: ProjectHistoryAction, project: SessionHistoryResponse['projects'][number]) => void;
  onNewProjectSession?: (project: SessionHistoryResponse['projects'][number]) => void;
  // Bottom zone — file tree of the focused session's project
  currentProject?: ProjectInfo | null;
  fileTree?: FileNode[];
  expandedPaths?: Set<string>;
  loadingPaths?: Set<string>;
  onTogglePath?: (path: string) => void;
  onSelectFile?: (path: string, type: 'file' | 'dir') => void;
  onFileAction?: (action: FileTreeAction, node: FileNode) => void;
  onOpenFolder?: () => void;
  onCloseProject?: () => void;
  onRefreshTree?: () => void | Promise<void>;
  isRefreshingProject?: boolean;
}

export const WorkspacePanel: React.FC<WorkspacePanelProps> = ({
  sessionHistory = null,
  sessions = [],
  agentProfiles,
  currentSession,
  currentProjectPath,
  onNewSession,
  onCompactSession,
  onRewindSession,
  onSwitchSession,
  onArchiveSession,
  onDeleteSession,
  onOpenProject,
  onOpenProjectModal,
  onProjectAction,
  onNewProjectSession,
  currentProject,
  fileTree = [],
  expandedPaths = new Set(),
  loadingPaths = new Set(),
  onTogglePath,
  onSelectFile,
  onFileAction,
  onOpenFolder,
  onCloseProject,
  onRefreshTree,
  isRefreshingProject = false,
}) => {
  const [initialLayout] = useState(loadLayout);
  const persistTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (persistTimerRef.current !== null) {
        window.clearTimeout(persistTimerRef.current);
      }
    };
  }, []);

  const persistLayout = useCallback((layout: Record<string, number>) => {
    if (persistTimerRef.current !== null) {
      window.clearTimeout(persistTimerRef.current);
    }
    persistTimerRef.current = window.setTimeout(() => {
      persistTimerRef.current = null;
      try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); } catch { /* ignore */ }
    }, 180);
  }, []);

  const handleLayoutChanged = useCallback((layout: Record<string, number>) => {
    persistLayout({
      'ws-sessions': layout['ws-sessions'] ?? DEFAULT_LAYOUT['ws-sessions'],
      'ws-files': layout['ws-files'] ?? DEFAULT_LAYOUT['ws-files'],
    });
  }, [persistLayout]);

  return (
    <Group
      id="workspace-split"
      orientation="vertical"
      defaultLayout={initialLayout}
      onLayoutChanged={handleLayoutChanged}
      className="flex flex-col h-full min-h-0"
    >
      {/* Top zone: projects + session history */}
      <Panel id="ws-sessions" defaultSize="58%" minSize="160px">
        <div className="h-full min-h-0 overflow-y-auto overscroll-contain pr-0.5 space-y-2">
          <button
            onClick={onNewSession}
            className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            /new
          </button>
          <div className="grid grid-cols-2 gap-1.5">
            <button
              type="button"
              onClick={onCompactSession}
              className="flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-xs bg-surface-alt text-fg-secondary hover:bg-surface-hover hover:text-fg transition-colors"
              title="Compact current session context"
            >
              <Archive className="w-3.5 h-3.5" />
              /compact
            </button>
            <button
              type="button"
              onClick={onRewindSession}
              className="flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-xs bg-surface-alt text-fg-secondary hover:bg-surface-hover hover:text-fg transition-colors"
              title="Rewind to a previous checkpoint"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              /rewind
            </button>
          </div>
          <SessionHistoryPanel
            history={sessionHistory}
            fallbackSessions={sessions}
            agentProfiles={agentProfiles}
            currentSession={currentSession}
            currentProjectPath={currentProjectPath}
            onSwitchSession={onSwitchSession}
            onArchiveSession={onArchiveSession}
            onDeleteSession={onDeleteSession}
            onOpenProject={onOpenProject}
            onOpenProjectModal={onOpenProjectModal}
            onProjectAction={onProjectAction}
            onNewProjectSession={onNewProjectSession}
          />
        </div>
      </Panel>

      <Separator className="my-1 h-2 border-t border-border transition-colors cursor-row-resize hover:border-accent/50 active:border-accent/70" />

      {/* Bottom zone: file tree of the focused session's project */}
      <Panel id="ws-files" defaultSize="42%" minSize="120px">
        {currentProject ? (
          <div className="h-full min-h-0 flex flex-col overflow-hidden">
            <ProjectPanel
              currentProject={currentProject}
              fileTree={fileTree}
              expandedPaths={expandedPaths}
              loadingPaths={loadingPaths}
              onTogglePath={onTogglePath || (() => {})}
              onSelectFile={onSelectFile || (() => {})}
              onFileAction={onFileAction}
              onOpenFolder={onOpenFolder || (() => {})}
              onOpenModal={onOpenProjectModal || (() => {})}
              onCloseProject={onCloseProject || (() => {})}
              onRefreshTree={onRefreshTree || (() => {})}
              isRefreshing={isRefreshingProject}
            />
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-xs text-fg-muted text-center px-3">
            <FolderOpen className="w-5 h-5 mb-2 opacity-30" />
            <p>No project for the focused session.</p>
            <button
              type="button"
              onClick={onOpenFolder}
              className="mt-2 text-accent hover:underline text-[11px]"
            >
              Open a folder
            </button>
          </div>
        )}
      </Panel>
    </Group>
  );
};
