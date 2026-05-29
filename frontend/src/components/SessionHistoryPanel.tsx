import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';
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
  SquarePen,
  Trash2,
  X,
} from 'lucide-react';
import type { AgentType, SessionHistoryItem, SessionHistoryProject, SessionHistoryResponse } from '../types';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from './ui/DropdownMenu';
import { cn } from './ui/cn';
import { displayNameForAgent, type AgentProfileMap } from '../lib/agentProfiles';

export type ProjectHistoryAction = 'pin' | 'unpin' | 'reveal' | 'worktree' | 'rename' | 'archive' | 'remove';

interface SessionHistoryPanelProps {
  history: SessionHistoryResponse | null;
  fallbackSessions?: SessionHistoryItem[];
  agentProfiles?: AgentProfileMap;
  currentSession?: string;
  currentProjectPath?: string | null;
  onSwitchSession?: (id: string, projectPath?: string | null) => void;
  onArchiveSession?: (id: string) => void;
  onDeleteSession?: (id: string) => void;
  onOpenProject?: (path: string) => void;
  onOpenProjectModal?: () => void;
  onProjectAction?: (action: ProjectHistoryAction, project: SessionHistoryProject) => void;
  onNewProjectSession?: (project: SessionHistoryProject) => void;
}

function projectKey(path?: string | null): string {
  return (path || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}

function projectIdentity(project: SessionHistoryProject): string {
  return project.project_key || projectKey(project.canonical_path || project.path);
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
  if (agentType?.startsWith('specialist:')) return 'Specialist';
  return agentType === 'coding' ? 'Coding' : 'Personal';
}

function isPrimaryPersonal(session: SessionHistoryItem): boolean {
  return !!session.is_primary || session.id === 'session_personal_main';
}

interface SessionRowProps {
  session: SessionHistoryItem;
  agentProfiles?: AgentProfileMap;
  isActive: boolean;
  menuOpen: boolean;
  onOpenMenu: (id: string | null) => void;
  onSwitch: (id: string, projectPath?: string | null) => void;
  onArchive: (id: string) => void;
  onDelete: (id: string) => void;
}

const SessionRow = memo(function SessionRow({
  session,
  agentProfiles,
  isActive,
  menuOpen,
  onOpenMenu,
  onSwitch,
  onArchive,
  onDelete,
}: SessionRowProps) {
  const primary = isPrimaryPersonal(session);
  const label = primary ? `${displayNameForAgent('personal', agentProfiles)} · Main` : formatSessionLabel(session);
  const type: AgentType = session.agent_type || 'personal';
  const badgeLabel = type.startsWith('specialist:') ? displayNameForAgent(type, agentProfiles) : agentLabel(type);
  const canManageSession = !primary && !session.is_running;

  const handleClick = useCallback(() => {
    onSwitch(session.id, session.project_path);
  }, [onSwitch, session.id, session.project_path]);

  const handleArchive = useCallback(() => {
    onOpenMenu(null);
    onArchive(session.id);
  }, [onArchive, onOpenMenu, session.id]);

  const handleDelete = useCallback(() => {
    onOpenMenu(null);
    onDelete(session.id);
  }, [onDelete, onOpenMenu, session.id]);

  const handleMenuOpenChange = useCallback((open: boolean) => {
    onOpenMenu(open ? session.id : null);
  }, [onOpenMenu, session.id]);

  const handleMenuTriggerClick = useCallback((event: React.MouseEvent) => {
    event.stopPropagation();
    onOpenMenu(session.id);
  }, [onOpenMenu, session.id]);

  return (
    <div
      className={cn(
        'group flex items-center justify-between gap-1 rounded px-2 py-1.5 text-xs transition-colors',
        isActive
          ? 'bg-surface-alt text-fg'
          : 'text-fg-secondary hover:bg-surface-hover hover:text-fg',
      )}
    >
      <button
        type="button"
        onClick={handleClick}
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
        title={label}
        aria-label={`Open session ${label}`}
      >
        <MessageSquare className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{label}</span>
        <span
          className={cn(
            'shrink-0 rounded px-1 py-0.5 text-[9px]',
            type === 'coding'
              ? 'bg-success/10 text-success'
              : type.startsWith('specialist:')
                ? 'bg-warning/10 text-warning'
                : 'bg-accent/10 text-accent',
          )}
        >
          {badgeLabel}
        </span>
      </button>
      <div className="flex min-w-[42px] items-center justify-end gap-1 text-[10px] text-fg-muted">
        {session.is_running ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-success" aria-label="Session running" />
        ) : (
          <span className="whitespace-nowrap group-hover:hidden">{formatRelativeTime(session.updated_at)}</span>
        )}
        {canManageSession && (
          <DropdownMenu open={menuOpen} onOpenChange={handleMenuOpenChange}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                onClick={handleMenuTriggerClick}
                className="rounded p-0.5 text-fg-muted opacity-0 transition-opacity hover:bg-surface-hover hover:text-fg group-hover:opacity-100"
                aria-label={`Session actions for ${label}`}
                title="Session actions"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[148px]">
              <DropdownMenuItem onSelect={handleArchive}>
                <Archive className="h-3.5 w-3.5" />
                <span>归档会话</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive onSelect={handleDelete}>
                <Trash2 className="h-3.5 w-3.5" />
                <span>永久删除</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  );
});

interface ProjectRowProps {
  project: SessionHistoryProject;
  identityKey: string;
  expanded: boolean;
  menuOpen: boolean;
  currentSession?: string;
  agentProfiles?: AgentProfileMap;
  openSessionMenuId: string | null;
  onToggle: (path: string) => void;
  onOpen: (path: string) => void;
  onOpenMenu: (key: string | null) => void;
  onAction: (action: ProjectHistoryAction, project: SessionHistoryProject) => void;
  onStartSession: (project: SessionHistoryProject) => void;
  onOpenSessionMenu: (id: string | null) => void;
  onSwitchSession: (id: string, projectPath?: string | null) => void;
  onArchiveSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
}

const ProjectRow = memo(function ProjectRow({
  project,
  identityKey,
  expanded,
  menuOpen,
  currentSession,
  agentProfiles,
  openSessionMenuId,
  onToggle,
  onOpen,
  onOpenMenu,
  onAction,
  onStartSession,
  onOpenSessionMenu,
  onSwitchSession,
  onArchiveSession,
  onDeleteSession,
}: ProjectRowProps) {
  const handleToggle = useCallback(() => onToggle(project.path), [onToggle, project.path]);
  const handleOpen = useCallback(() => onOpen(project.path), [onOpen, project.path]);
  const handleStart = useCallback((event: React.MouseEvent) => {
    event.stopPropagation();
    onStartSession(project);
  }, [onStartSession, project]);
  const handleContextMenu = useCallback((event: React.MouseEvent) => {
    event.preventDefault();
    onOpenMenu(identityKey);
  }, [onOpenMenu, identityKey]);
  const handleMenuTriggerClick = useCallback((event: React.MouseEvent) => {
    event.stopPropagation();
    onOpenMenu(identityKey);
  }, [onOpenMenu, identityKey]);
  const handleMenuOpenChange = useCallback((open: boolean) => {
    onOpenMenu(open ? identityKey : null);
  }, [onOpenMenu, identityKey]);
  const handleAction = useCallback((action: ProjectHistoryAction) => {
    onOpenMenu(null);
    onAction(action, project);
  }, [onAction, onOpenMenu, project]);

  return (
    <div className="space-y-0.5">
      <div
        className={cn(
          'group flex items-center gap-1 rounded px-1 py-1 text-xs transition-colors',
          project.is_current ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:bg-surface-hover hover:text-fg',
        )}
        onContextMenu={handleContextMenu}
      >
        <button
          type="button"
          onClick={handleToggle}
          className="rounded p-0.5 text-fg-muted hover:bg-surface-hover hover:text-fg"
          aria-label={`${expanded ? 'Collapse' : 'Expand'} project ${project.name}`}
          title={expanded ? 'Collapse project' : 'Expand project'}
        >
          <ChevronRight className={cn('h-3 w-3 transition-transform', expanded && 'rotate-90')} />
        </button>
        <button
          type="button"
          onClick={handleOpen}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
          title={project.path}
          aria-label={`Open project ${project.name}`}
        >
          <Folder className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{project.name}</span>
        </button>
        <div className="flex shrink-0 items-center gap-0.5">
          {project.has_running && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-success" aria-label="Project running" />
          )}
          <DropdownMenu open={menuOpen} onOpenChange={handleMenuOpenChange}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                onClick={handleMenuTriggerClick}
                className={cn(
                  'rounded p-0.5 text-fg-muted opacity-0 transition-opacity hover:bg-surface-hover hover:text-fg group-hover:opacity-100',
                  (project.is_current || menuOpen) && 'opacity-100',
                )}
                aria-label={`Project actions for ${project.name}`}
                title="Project actions"
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[184px]">
              <DropdownMenuItem onSelect={() => handleAction(project.is_pinned ? 'unpin' : 'pin')}>
                <Pin className="h-3.5 w-3.5" />
                <span>{project.is_pinned ? '取消置顶' : '置顶项目'}</span>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => handleAction('reveal')}>
                <FolderOpen className="h-3.5 w-3.5" />
                <span>在资源管理器中打开</span>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => handleAction('worktree')}>
                <GitBranch className="h-3.5 w-3.5" />
                <span>创建永久工作树</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => handleAction('rename')}>
                <Pencil className="h-3.5 w-3.5" />
                <span>重命名项目</span>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => handleAction('archive')}>
                <Archive className="h-3.5 w-3.5" />
                <span>归档会话</span>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive onSelect={() => handleAction('remove')}>
                <X className="h-3.5 w-3.5" />
                <span>移除</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            type="button"
            onClick={handleStart}
            className={cn(
              'rounded p-0.5 text-fg-muted opacity-0 transition-opacity hover:bg-surface-hover hover:text-fg group-hover:opacity-100',
              project.is_current && 'opacity-100',
            )}
            aria-label={`Start new session in ${project.name}`}
            title={`在 ${project.name} 中开始新对话`}
          >
            <SquarePen className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      {expanded && project.sessions.length > 0 && (
        <div className="ml-5 space-y-0.5">
          {project.sessions.map((session) => (
            <SessionRow
              key={session.id}
              session={session}
              agentProfiles={agentProfiles}
              isActive={session.id === currentSession}
              menuOpen={openSessionMenuId === session.id}
              onOpenMenu={onOpenSessionMenu}
              onSwitch={onSwitchSession}
              onArchive={onArchiveSession}
              onDelete={onDeleteSession}
            />
          ))}
        </div>
      )}
    </div>
  );
});

export const SessionHistoryPanel: React.FC<SessionHistoryPanelProps> = ({
  history,
  fallbackSessions = [],
  agentProfiles,
  currentSession,
  currentProjectPath,
  onSwitchSession,
  onArchiveSession,
  onDeleteSession,
  onOpenProject,
  onOpenProjectModal,
  onProjectAction,
  onNewProjectSession,
}) => {
  const projects = history?.projects || [];
  const standaloneSessions = history?.standalone_sessions || fallbackSessions;
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(() => new Set());
  const [openProjectMenu, setOpenProjectMenu] = useState<string | null>(null);
  const [openSessionMenu, setOpenSessionMenu] = useState<string | null>(null);

  const currentProjectKey = projectKey(currentProjectPath);

  // Stable signature of which projects should be auto-expanded. Using the
  // signature (rather than `projects` itself) keeps this effect quiet during
  // 5s polling where projects gets a fresh array reference each tick.
  const autoExpandSignature = useMemo(() => {
    return projects
      .map((project) => {
        if (project.is_current || project.has_running || projectKey(project.path) === currentProjectKey) {
          return projectIdentity(project) || '';
        }
        return '';
      })
      .filter(Boolean)
      .join('|');
  }, [projects, currentProjectKey]);

  useEffect(() => {
    if (!autoExpandSignature) return;
    setExpandedProjects((prev) => {
      const keys = autoExpandSignature.split('|');
      let changed = false;
      const next = new Set(prev);
      for (const key of keys) {
        if (key && !next.has(key)) {
          next.add(key);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [autoExpandSignature]);

  const hasAnySession = useMemo(() => (
    standaloneSessions.length > 0 || projects.some((project) => project.sessions.length > 0)
  ), [projects, standaloneSessions.length]);

  const toggleProject = useCallback((path: string) => {
    const key = projectKey(path);
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const openProject = useCallback((path: string) => {
    const key = projectKey(path);
    setExpandedProjects((prev) => {
      if (prev.has(key)) return prev;
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    onOpenProject?.(path);
  }, [onOpenProject]);

  const startProjectSession = useCallback((project: SessionHistoryProject) => {
    const key = projectIdentity(project);
    setExpandedProjects((prev) => {
      if (prev.has(key)) return prev;
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    onNewProjectSession?.(project);
  }, [onNewProjectSession]);

  const handleProjectAction = useCallback((action: ProjectHistoryAction, project: SessionHistoryProject) => {
    onProjectAction?.(action, project);
  }, [onProjectAction]);

  const handleSwitchSession = useCallback((id: string, projectPath?: string | null) => {
    onSwitchSession?.(id, projectPath);
  }, [onSwitchSession]);

  const handleArchiveSession = useCallback((id: string) => {
    onArchiveSession?.(id);
  }, [onArchiveSession]);

  const handleDeleteSession = useCallback((id: string) => {
    onDeleteSession?.(id);
  }, [onDeleteSession]);

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
          const identityKey = projectIdentity(project) || projectKey(project.path);
          const expanded = expandedProjects.has(identityKey);
          return (
            <ProjectRow
              key={identityKey || project.path}
              project={project}
              identityKey={identityKey}
              expanded={expanded}
              menuOpen={openProjectMenu === identityKey}
              currentSession={currentSession}
              agentProfiles={agentProfiles}
              openSessionMenuId={openSessionMenu}
              onToggle={toggleProject}
              onOpen={openProject}
              onOpenMenu={setOpenProjectMenu}
              onAction={handleProjectAction}
              onStartSession={startProjectSession}
              onOpenSessionMenu={setOpenSessionMenu}
              onSwitchSession={handleSwitchSession}
              onArchiveSession={handleArchiveSession}
              onDeleteSession={handleDeleteSession}
            />
          );
        })}
      </div>

      <div className="space-y-1">
        <div className="px-1 text-xs text-fg-muted">对话</div>
        {standaloneSessions.length > 0 ? (
          <div className="space-y-0.5">
            {standaloneSessions.map((session) => (
              <SessionRow
                key={session.id}
                session={session}
                agentProfiles={agentProfiles}
                isActive={session.id === currentSession}
                menuOpen={openSessionMenu === session.id}
                onOpenMenu={setOpenSessionMenu}
                onSwitch={handleSwitchSession}
                onArchive={handleArchiveSession}
                onDelete={handleDeleteSession}
              />
            ))}
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
