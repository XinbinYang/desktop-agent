import React, { useEffect, useMemo, useState } from 'react';
import {
  Archive,
  ChevronRight,
  Folder,
  FolderOpen,
  FolderPlus,
  GitBranch,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  Pin,
  X,
} from 'lucide-react';
import type { AgentType, SessionHistoryItem, SessionHistoryProject, SessionHistoryResponse } from '../types';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from './ui/DropdownMenu';
import { cn } from './ui/cn';

export type ProjectHistoryAction = 'pin' | 'unpin' | 'reveal' | 'worktree' | 'rename' | 'archive' | 'remove';

interface SessionHistoryPanelProps {
  history: SessionHistoryResponse | null;
  fallbackSessions?: SessionHistoryItem[];
  currentSession?: string;
  currentProjectPath?: string | null;
  onSwitchSession?: (id: string, projectPath?: string | null) => void;
  onDeleteSession?: (id: string) => void;
  onOpenProject?: (path: string) => void;
  onOpenProjectModal?: () => void;
  onProjectAction?: (action: ProjectHistoryAction, project: SessionHistoryProject) => void;
}

function projectKey(path?: string | null): string {
  return (path || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}

function formatSessionLabel(session: SessionHistoryItem): string {
  const title = (session.title || '').trim();
  if (title) return title.length > 28 ? `${title.slice(0, 28)}...` : title;
  const shortId = session.id
    .replace(/^session_personal_/, '')
    .replace(/^session_coding_/, '')
    .replace(/^session_/, '');
  return shortId.length > 28 ? `${shortId.slice(0, 28)}...` : shortId;
}

function formatRelativeTime(timestamp?: number): string {
  if (!timestamp) return '';
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  if (seconds < 60) return '刚刚';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时`;
  const days = Math.floor(hours / 24);
  if (days < 14) return `${days} 天`;
  return `${Math.max(1, Math.floor(days / 7))} 周`;
}

function agentLabel(agentType?: AgentType): string {
  return agentType === 'coding' ? 'Coding' : 'Personal';
}

function isPrimaryPersonal(session: SessionHistoryItem): boolean {
  return !!session.is_primary || session.id === 'session_personal_main';
}

export const SessionHistoryPanel: React.FC<SessionHistoryPanelProps> = ({
  history,
  fallbackSessions = [],
  currentSession,
  currentProjectPath,
  onSwitchSession,
  onDeleteSession,
  onOpenProject,
  onOpenProjectModal,
  onProjectAction,
}) => {
  const projects = history?.projects || [];
  const standaloneSessions = history?.standalone_sessions || fallbackSessions;
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(() => new Set());
  const [openProjectMenu, setOpenProjectMenu] = useState<string | null>(null);

  useEffect(() => {
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      let changed = false;
      for (const project of projects) {
        if (project.is_current || project.has_running || projectKey(project.path) === projectKey(currentProjectPath)) {
          const key = projectKey(project.path);
          if (key && !next.has(key)) {
            next.add(key);
            changed = true;
          }
        }
      }
      return changed ? next : prev;
    });
  }, [currentProjectPath, projects]);

  const hasAnySession = useMemo(() => (
    standaloneSessions.length > 0 || projects.some((project) => project.sessions.length > 0)
  ), [projects, standaloneSessions.length]);

  const toggleProject = (path: string) => {
    const key = projectKey(path);
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const openProject = (path: string) => {
    const key = projectKey(path);
    setExpandedProjects((prev) => new Set(prev).add(key));
    onOpenProject?.(path);
  };

  const handleProjectAction = (action: ProjectHistoryAction, project: SessionHistoryProject) => {
    setOpenProjectMenu(null);
    onProjectAction?.(action, project);
  };

  const renderProjectMenu = (project: SessionHistoryProject, key: string) => (
    <DropdownMenu open={openProjectMenu === key} onOpenChange={(open) => setOpenProjectMenu(open ? key : null)}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            setOpenProjectMenu(key);
          }}
          className={cn(
            'rounded p-0.5 text-fg-muted opacity-0 transition-opacity hover:bg-surface-hover hover:text-fg group-hover:opacity-100',
            (project.is_current || openProjectMenu === key) && 'opacity-100',
          )}
          aria-label={`Project actions for ${project.name}`}
          title="Project actions"
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[184px]">
        <DropdownMenuItem onSelect={() => handleProjectAction(project.is_pinned ? 'unpin' : 'pin', project)}>
          <Pin className="h-3.5 w-3.5" />
          <span>{project.is_pinned ? '取消置顶' : '置顶项目'}</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => handleProjectAction('reveal', project)}>
          <FolderOpen className="h-3.5 w-3.5" />
          <span>在资源管理器中打开</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => handleProjectAction('worktree', project)}>
          <GitBranch className="h-3.5 w-3.5" />
          <span>创建永久工作树</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => handleProjectAction('rename', project)}>
          <Pencil className="h-3.5 w-3.5" />
          <span>重命名项目</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => handleProjectAction('archive', project)}>
          <Archive className="h-3.5 w-3.5" />
          <span>归档对话</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={() => handleProjectAction('remove', project)}>
          <X className="h-3.5 w-3.5" />
          <span>移除</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const renderSession = (session: SessionHistoryItem) => {
    const label = isPrimaryPersonal(session) ? 'Personal Agent · Main' : formatSessionLabel(session);
    const type = session.agent_type || 'personal';
    return (
      <div
        key={session.id}
        className={cn(
          'group flex items-center justify-between gap-1 rounded px-2 py-1.5 text-xs transition-colors',
          session.id === currentSession
            ? 'bg-surface-alt text-fg'
            : 'text-fg-secondary hover:bg-surface-hover hover:text-fg',
        )}
      >
        <button
          type="button"
          onClick={() => onSwitchSession?.(session.id, session.project_path)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          title={label}
          aria-label={`Open session ${label}`}
        >
          <MessageSquare className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{label}</span>
          <span
            className={cn(
              'shrink-0 rounded px-1 py-0.5 text-[9px]',
              type === 'coding' ? 'bg-success/10 text-success' : 'bg-accent/10 text-accent',
            )}
          >
            {agentLabel(type)}
          </span>
        </button>
        <div className="flex min-w-[34px] items-center justify-end gap-1 text-[10px] text-fg-muted">
          {session.is_running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-success" aria-label="Session running" />
          ) : (
            <span className="whitespace-nowrap group-hover:hidden">{formatRelativeTime(session.updated_at)}</span>
          )}
          {!isPrimaryPersonal(session) && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onDeleteSession?.(session.id);
              }}
              className={cn(
                'rounded p-0.5 text-fg-muted opacity-0 transition-opacity hover:bg-surface-hover hover:text-danger group-hover:opacity-100',
                session.is_running && 'opacity-0',
              )}
              aria-label={`Delete session ${label}`}
              title="Delete session"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <div className="px-1 text-xs text-fg-muted">项目</div>
        <button
          type="button"
          onClick={onOpenProjectModal}
          className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-fg-secondary transition-colors hover:bg-surface-hover hover:text-fg"
        >
          <FolderPlus className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">New project</span>
        </button>
        {projects.map((project) => {
          const key = projectKey(project.path);
          const expanded = expandedProjects.has(key);
          return (
            <div key={project.path} className="space-y-0.5">
              <div
                className={cn(
                  'group flex items-center gap-1 rounded px-1 py-1 text-xs transition-colors',
                  project.is_current ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:bg-surface-hover hover:text-fg',
                )}
                onContextMenu={(event) => {
                  event.preventDefault();
                  setOpenProjectMenu(key);
                }}
              >
                <button
                  type="button"
                  onClick={() => toggleProject(project.path)}
                  className="rounded p-0.5 text-fg-muted hover:bg-surface-hover hover:text-fg"
                  aria-label={`${expanded ? 'Collapse' : 'Expand'} project ${project.name}`}
                  title={expanded ? 'Collapse project' : 'Expand project'}
                >
                  <ChevronRight className={cn('h-3 w-3 transition-transform', expanded && 'rotate-90')} />
                </button>
                <button
                  type="button"
                  onClick={() => openProject(project.path)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  title={project.path}
                  aria-label={`Open project ${project.name}`}
                >
                  <Folder className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{project.name}</span>
                </button>
                {project.has_running && (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-success" aria-label="Project running" />
                )}
                {renderProjectMenu(project, key)}
              </div>
              {expanded && project.sessions.length > 0 && (
                <div className="ml-5 space-y-0.5">
                  {project.sessions.map(renderSession)}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="space-y-1">
        <div className="px-1 text-xs text-fg-muted">对话</div>
        {standaloneSessions.length > 0 ? (
          <div className="space-y-0.5">
            {standaloneSessions.map(renderSession)}
          </div>
        ) : (
          <div className="px-2 py-2 text-xs text-fg-muted">暂无聊天</div>
        )}
      </div>

      {!hasAnySession && projects.length === 0 && (
        <div className="py-4 text-center text-xs text-fg-muted">No sessions yet</div>
      )}
    </div>
  );
};
