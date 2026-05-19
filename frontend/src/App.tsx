import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { Panel, Group, Separator } from 'react-resizable-panels';
import type { GroupImperativeHandle, PanelImperativeHandle } from 'react-resizable-panels';
import { AnimatePresence, motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { Sidebar } from './components/Sidebar';
import type { ProjectHistoryAction } from './components/SessionHistoryPanel';
import { SessionView, type SessionViewHandle } from './components/session/SessionView';
import { PaneRenderer } from './components/session/PaneRenderer';
import type { LeafNode, PaneNode, SessionPane, SplitNode } from './components/session/PaneTypes';
import {
  nextNodeId,
  collectLeaves,
  collectLeafNodes,
  findLeafById,
  findLeafByPaneId,
  findFirstLeafId,
  replaceNode,
  removeLeaf,
  serializePaneTree,
  deserializePaneTree,
  updateSplitSizes,
  resetSplitSizes,
} from './components/session/PaneTypes';
import { TerminalPanel } from './components/TerminalPanel';
import { WorkspacePanel, type WorkspaceView } from './components/workspace/WorkspacePanel';
import { ActivityPanel } from './components/activity/ActivityPanel';
import { PersonalWorkspacePanel } from './components/PersonalWorkspace/PersonalWorkspacePanel';
import { SwitchAgentModal } from './components/SwitchAgentModal';
import type { SessionSnapshot, SessionActions } from './contexts/FocusedSessionContext';
import { FocusedDataProvider, FocusedActionsProvider } from './contexts/FocusedSessionContext';
import { ModelInfo, ProjectInfo, FileNode, SettingsResponse, type AgentType, type SessionHistoryItem, type SessionHistoryProject, type SessionHistoryResponse } from './types';
import { API_BASE } from './config';
import { deleteDraft, deleteSessionData } from './lib/db';
import {
  DEFAULT_MAIN_LAYOUT,
  DEFAULT_SIDEBAR_WIDTH,
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  DEFAULT_TERMINAL_LAYOUT,
  useLayoutState,
  type PanelLayout,
} from './hooks/useLayoutState';
import { getLangFromFilename } from './lib/language';
import { AGENT_LABEL, agentForRole, normalizeAgentType, roleForAgent } from './lib/agentProfiles';
import { Settings, ChevronDown, ChevronUp, ChevronLeft, Monitor, Activity } from 'lucide-react';
import type { Team } from './lib/teamStore';
import { loadTeams, saveTeams, createTeam, addPaneToTeam, removePaneFromTeam } from './lib/teamStore';
import { ProjectModal } from './components/ProjectModal';
import { ProjectRenameDialog } from './components/ProjectRenameDialog';
import { ProjectHistoryConfirmDialog } from './components/ProjectHistoryConfirmDialog';
import { SessionDeleteConfirmDialog } from './components/SessionDeleteConfirmDialog';
import { SettingsModal } from './components/SettingsModal';
import { ActivityBar } from './components/ActivityBar';
import { WindowControls } from './components/WindowControls';
import type { FileTreeAction } from './components/FileTree';

type SessionListItem = SessionHistoryItem;

interface ResolvedSession {
  session_id: string;
  agent_type: AgentType;
  role_id: string;
  model_id: string;
  title?: string;
  project_path?: string | null;
  created?: boolean;
  is_primary?: boolean;
}

interface PendingProjectFileOpen {
  sessionId: string;
  path: string;
  content: string;
  language: string;
  openToSide?: boolean;
}

type SplitPlacement = 'before' | 'after';

interface SplitPaneOptions {
  sessionId?: string;
  placement?: SplitPlacement;
  model?: string;
  role?: string;
  agentType?: AgentType;
}

const RESIZE_TARGET_MINIMUM_SIZE = { fine: 4, coarse: 34 } as const;

function clampSidebarWidth(width: number): number {
  return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, width));
}

function providerNeedsSetup(provider: SettingsResponse['providers'][string] | undefined): boolean {
  if (!provider) return true;
  if (typeof provider.api_key_configured === 'boolean') {
    return !provider.api_key_configured;
  }
  const masked = provider.api_key_masked || '';
  return !masked || (masked.startsWith('${') && masked.endsWith('}'));
}

function providerForModel(settings: SettingsResponse, modelId: string | undefined): SettingsResponse['providers'][string] | undefined {
  if (!modelId) return undefined;
  const providers = Object.values(settings.providers || {});
  const matched = providers.find((provider) =>
    (provider.models || []).some((model) => model.id === modelId)
  );
  if (matched) return matched;
  const providersWithoutModelLists = providers.filter((provider) => (provider.models || []).length === 0);
  return providers.length === 1 && providersWithoutModelLists.length === 1
    ? providersWithoutModelLists[0]
    : undefined;
}

function defaultProviderNeedsSetup(settings: SettingsResponse | null): boolean {
  if (!settings?.providers) return false;
  const personalModel = settings.personal_agent?.model;
  const codingModel = settings.coding_agent?.model;
  if (!personalModel && !codingModel) return true;
  return [personalModel, codingModel]
    .filter(Boolean)
    .some((modelId) => providerNeedsSetup(providerForModel(settings, modelId)));
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, '/').toLowerCase();
}

const PANE_TREE_STORAGE_KEY = 'desktop-agent-pane-tree';

function createDefaultSessionId(agentType: AgentType): string {
  return agentType === 'personal'
    ? 'session_personal_main'
    : `session_coding_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function createSessionPane(agentType: AgentType, model: string, sessionId = createDefaultSessionId(agentType)): SessionPane {
  return {
    id: `pane_${Date.now()}`,
    sessionId,
    model,
    agentType,
    role: roleForAgent(agentType),
    isPrimary: agentType === 'personal',
  };
}

function createLeaf(agentType: AgentType, model: string, sessionId?: string): LeafNode {
  return {
    type: 'leaf',
    id: nextNodeId(),
    pane: createSessionPane(agentType, model, sessionId),
  };
}

function createDefaultPaneTree(agentType: AgentType): PaneNode {
  return createLeaf(agentType, '');
}

function loadPersistedPaneTree(activeAgent: AgentType): { paneRoot: PaneNode; focusedLeafId: string } {
  try {
    const raw = localStorage.getItem(PANE_TREE_STORAGE_KEY);
    if (!raw) throw new Error('no persisted tree');
    const data = deserializePaneTree(raw);
    if (!data) throw new Error('deserialize failed');
    // Validate: focusedLeafId should exist in tree
    const leaf = findLeafById(data.paneRoot, data.focusedLeafId);
    if (!leaf) {
      data.focusedLeafId = findFirstLeafId(data.paneRoot) ?? data.focusedLeafId;
    }
    return { paneRoot: data.paneRoot, focusedLeafId: data.focusedLeafId };
  } catch {
    const def = createDefaultPaneTree(activeAgent);
    return { paneRoot: def, focusedLeafId: def.id };
  }
}

function mapPaneTree(root: PaneNode, mapper: (pane: SessionPane) => SessionPane): PaneNode {
  if (root.type === 'leaf') {
    return { ...root, pane: mapper(root.pane) };
  }
  return { ...root, children: root.children.map((child) => mapPaneTree(child, mapper)) };
}

function sessionShortId(sessionId: string): string {
  return sessionId
    .replace(/^session_personal_/, '')
    .replace(/^session_coding_/, '')
    .replace(/^session_/, '#');
}

function sessionTitleForDisplay(pane: SessionPane | null | undefined, meta?: SessionListItem): string {
  if (!pane) return 'No Session';
  const agentType = pane.agentType || normalizeAgentType(meta?.agent_type, meta?.role_id);
  if (agentType === 'personal' && (pane.isPrimary || meta?.is_primary || pane.sessionId === 'session_personal_main')) {
    return 'Personal Agent · Main';
  }
  const title = (meta?.title || pane.title || '').trim();
  const label = title || sessionShortId(pane.sessionId);
  return `${AGENT_LABEL[agentType]} · ${label}`;
}

function sessionModelForPane(pane: SessionPane | null | undefined, meta?: SessionListItem): string {
  return pane?.model || meta?.model_id || '';
}

function flattenSessionHistory(history: SessionHistoryResponse | null): SessionListItem[] {
  if (!history) return [];
  const byId = new Map<string, SessionListItem>();
  for (const session of history.standalone_sessions || []) {
    byId.set(session.id, session);
  }
  for (const project of history.projects || []) {
    for (const session of project.sessions || []) {
      byId.set(session.id, session);
    }
  }
  return Array.from(byId.values()).sort((a, b) => {
    if (a.is_primary && !b.is_primary) return -1;
    if (!a.is_primary && b.is_primary) return 1;
    return (b.updated_at || 0) - (a.updated_at || 0);
  });
}

function findFileNode(nodes: FileNode[], path: string): FileNode | undefined {
  for (const node of nodes) {
    if (node.path === path) return node;
    if (node.children) {
      const found = findFileNode(node.children, path);
      if (found) return found;
    }
  }
  return undefined;
}

function withDirectoryChildren(nodes: FileNode[], path: string, children: FileNode[]): FileNode[] {
  return nodes.map((node) => {
    if (node.path === path) return { ...node, children };
    if (!node.children) return node;
    return { ...node, children: withDirectoryChildren(node.children, path, children) };
  });
}

function normalizeProjectPath(path: string): string {
  return (path || '').replace(/\\/g, '/').replace(/\/+$/, '');
}

function projectAbsolutePath(project: ProjectInfo, relativePath: string): string {
  const root = normalizeProjectPath(project.path);
  const rel = (relativePath || '').replace(/\\/g, '/').replace(/^\/+/, '');
  return rel ? `${root}/${rel}` : root;
}

function projectParentPath(project: ProjectInfo, node: FileNode): string {
  if (node.type === 'dir') return projectAbsolutePath(project, node.path);
  const normalized = node.path.replace(/\\/g, '/');
  const idx = normalized.lastIndexOf('/');
  return idx >= 0 ? projectAbsolutePath(project, normalized.slice(0, idx)) : normalizeProjectPath(project.path);
}

function isProjectContained(project: ProjectInfo, absolutePath: string): boolean {
  const root = normalizeProjectPath(project.path).toLowerCase();
  const target = normalizeProjectPath(absolutePath).toLowerCase();
  return target === root || target.startsWith(`${root}/`);
}

function editorPathMatches(openPath: string, targetPath: string, includeChildren = false): boolean {
  const open = normalizePath(openPath);
  const target = normalizePath(targetPath);
  return includeChildren ? open === target || open.startsWith(`${target}/`) : open === target;
}

function apiErrorMessage(error: unknown): string {
  if (!error) return 'Unknown error';
  if (typeof error === 'string') return error;
  if (typeof error === 'object' && 'message' in error) {
    return String((error as { message?: unknown }).message || 'Unknown error');
  }
  return JSON.stringify(error);
}

const NOOP_ACTIONS: SessionActions = {
  sendMessage: () => {},
  clearSession: () => {},
  compactSession: () => {},
  loadCheckpoints: async () => [],
  rewindToCheckpoint: () => {},
  stopRunning: () => {},
  retryLast: () => {},
  switchModel: () => {},
  switchRole: () => {},
  executeToolDirect: () => {},
  addTerminalLog: (_msg: string) => {},
  approvePlan: () => {},
  buildPlan: () => {},
  pauseBuild: () => {},
  endBuild: () => {},
  rejectPlan: () => {},
  updatePlanDecision: () => {},
  submitPlanDecisions: () => {},
  onSelectFileInEditor: () => {},
  onCloseFileInEditor: () => {},
  onFileContentChange: () => {},
  onSaveFile: () => {},
  saveInputDraft: async () => {},
  loadInputDraft: async () => undefined,
  clearInputDraft: async () => {},
  runAction: async () => {},
  openRunWorktree: async () => {},
  handleOpenFileFromPanel: () => {},
  handleOpenFileFromPanelWithLine: () => {},
};

export default function App() {
  const { t } = useTranslation();
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [agentModels, setAgentModels] = useState<Record<string, string>>({ personal: '', coding: '' });
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  // Pane tree — restored from localStorage or fresh default
  const initialPaneTree = React.useMemo(() => loadPersistedPaneTree('personal'), []);
  const [paneRoot, setPaneRoot] = useState<PaneNode>(() => initialPaneTree.paneRoot);
  const [focusedLeafId, setFocusedLeafId] = useState<string>(() => initialPaneTree.focusedLeafId);
  const focusedSessionId = React.useMemo(() => {
    const leaf = findLeafById(paneRoot, focusedLeafId);
    return leaf?.pane.sessionId ?? collectLeaves(paneRoot)[0]?.sessionId ?? '';
  }, [paneRoot, focusedLeafId]);
  const [sessionHistory, setSessionHistory] = useState<SessionHistoryResponse | null>(null);
  const sessions = React.useMemo(() => flattenSessionHistory(sessionHistory), [sessionHistory]);
  const [showSettings, setShowSettings] = useState(false);

  const [currentProject, setCurrentProject] = useState<ProjectInfo | null>(null);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [showProjectModal, setShowProjectModal] = useState(false);
  const [renameProjectTarget, setRenameProjectTarget] = useState<SessionHistoryProject | null>(null);
  const [renameProjectError, setRenameProjectError] = useState('');
  const [isRenamingProject, setIsRenamingProject] = useState(false);
  const [confirmProjectAction, setConfirmProjectAction] = useState<{
    action: 'archive' | 'remove';
    project: SessionHistoryProject;
  } | null>(null);
  const [confirmProjectError, setConfirmProjectError] = useState('');
  const [isConfirmingProjectAction, setIsConfirmingProjectAction] = useState(false);
  const [deleteSessionTarget, setDeleteSessionTarget] = useState<SessionHistoryItem | null>(null);
  const [deleteSessionError, setDeleteSessionError] = useState('');
  const [isDeletingSession, setIsDeletingSession] = useState(false);
  const [isRefreshingProject, setIsRefreshingProject] = useState(false);

  const layout = useLayoutState();
  const [sidebarDragWidth, setSidebarDragWidth] = useState<number | null>(null);
  const sidebarWidth = sidebarDragWidth ?? layout.sidebarWidth;
  const agentModel = agentModels[layout.activeAgent] || '';
  const sessionMetaById = React.useMemo(() => {
    const map: Record<string, SessionListItem> = {};
    for (const session of sessions) map[session.id] = session;
    return map;
  }, [sessions]);
  const focusedLeaf = React.useMemo(() => findLeafById(paneRoot, focusedLeafId), [paneRoot, focusedLeafId]);
  const focusedPane = focusedLeaf?.pane ?? null;
  const focusedSessionMeta = focusedPane ? sessionMetaById[focusedPane.sessionId] : undefined;
  const focusedAgentType = focusedPane?.agentType || layout.activeAgent;
  const focusedModel = sessionModelForPane(focusedPane, focusedSessionMeta) || agentModels[focusedAgentType] || agentModel;
  const focusedTitle = sessionTitleForDisplay(focusedPane, focusedSessionMeta);

  // Agent switch suggestion from backend auto-dispatch
  const [switchSuggestion, setSwitchSuggestion] = useState<{
    from: AgentType; to: AgentType; reason: string;
  } | null>(null);

  const [teams, setTeams] = useState<Team[]>(loadTeams);

  const [focusedSnapshot, setFocusedSnapshot] = useState<SessionSnapshot | null>(null);
  const [focusedActions, setFocusedActions] = useState<SessionActions>(NOOP_ACTIONS);
  // Per-agent "is any session running" — drives the persistent spinner on the
  // ActivityBar agent buttons so a backgrounded agent's work stays visible.
  // Server truth (session-history poll) plus the focused pane's live snapshot.
  const agentRunningState = React.useMemo(() => {
    let personal = false;
    let coding = false;
    for (const s of sessions) {
      if (!s.is_running) continue;
      if ((s.agent_type || 'personal') === 'coding') coding = true;
      else personal = true;
    }
    if (focusedSnapshot?.isRunning) {
      if (focusedAgentType === 'coding') coding = true;
      else personal = true;
    }
    return { personal, coding };
  }, [sessions, focusedSnapshot?.isRunning, focusedAgentType]);
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>('editor');

  const previewUrl = React.useMemo(() => {
    const arts = focusedSnapshot?.artifacts;
    if (!arts) return undefined;
    for (let i = arts.length - 1; i >= 0; i--) {
      if (arts[i].type === 'web') return arts[i].url;
    }
    return undefined;
  }, [focusedSnapshot?.artifacts]);

  const sessionViewRefs = useRef<Map<string, SessionViewHandle>>(new Map());
  const newSessionRef = useRef<() => void>(() => {});
  const lastFocusedLeafByAgent = useRef<Partial<Record<AgentType, string>>>({});
  const didPromptModelSetup = React.useRef(false);
  const mainGroupRef = useRef<GroupImperativeHandle>(null);
  const centerGroupRef = useRef<GroupImperativeHandle>(null);
  const rightPanelRef = useRef<PanelImperativeHandle>(null);
  const terminalPanelRef = useRef<PanelImperativeHandle>(null);
  const projectRefreshTimerRef = useRef<number | null>(null);
  const pendingProjectFileOpenRef = useRef<PendingProjectFileOpen | null>(null);
  const manualProjectLockLeafRef = useRef<string | null>(null);

  const handleSidebarResizeStart = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = sidebarWidth;
    let latestWidth = startWidth;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMove = (moveEvent: PointerEvent) => {
      latestWidth = clampSidebarWidth(startWidth + moveEvent.clientX - startX);
      setSidebarDragWidth(latestWidth);
    };

    const finishResize = () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerup', finishResize);
      window.removeEventListener('pointercancel', finishResize);
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      setSidebarDragWidth(null);
      layout.setSidebarWidth(latestWidth);
    };

    window.addEventListener('pointermove', handleMove);
    window.addEventListener('pointerup', finishResize);
    window.addEventListener('pointercancel', finishResize);
  }, [layout, sidebarWidth]);

  const handleSidebarResizeKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight' && event.key !== 'Home') return;
    event.preventDefault();
    if (event.key === 'Home') {
      layout.setSidebarWidth(DEFAULT_SIDEBAR_WIDTH);
      return;
    }
    const delta = event.key === 'ArrowRight' ? 16 : -16;
    layout.setSidebarWidth(layout.sidebarWidth + delta);
  }, [layout]);

  useEffect(() => {
    const panel = rightPanelRef.current;
    if (!panel) return;
    if (layout.rightPanelVisible && panel.isCollapsed()) {
      panel.expand();
    } else if (!layout.rightPanelVisible && !panel.isCollapsed()) {
      panel.collapse();
    }
  }, [layout.rightPanelVisible]);

  useEffect(() => {
    const panel = terminalPanelRef.current;
    if (!panel) return;
    if (layout.showTerminal && panel.isCollapsed()) {
      panel.expand();
    } else if (!layout.showTerminal && !panel.isCollapsed()) {
      panel.collapse();
    }
  }, [layout.showTerminal]);

  // Persist pane tree to localStorage on change
  useEffect(() => {
    try {
      const raw = serializePaneTree(paneRoot, focusedLeafId);
      localStorage.setItem(PANE_TREE_STORAGE_KEY, raw);
    } catch { /* ignore */ }
  }, [paneRoot, focusedLeafId]);

  useEffect(() => {
    if (sessions.length === 0) return;
    setPaneRoot((prev) => {
      let changed = false;
      const next = mapPaneTree(prev, (pane) => {
        const meta = sessionMetaById[pane.sessionId];
        if (!meta) return pane;
        const agentType = normalizeAgentType(meta.agent_type, meta.role_id);
        const updated: SessionPane = {
          ...pane,
          model: meta.model_id || pane.model,
          agentType,
          role: meta.role_id || roleForAgent(agentType),
          title: meta.title || pane.title,
          isPrimary: !!meta.is_primary,
          projectPath: meta.project_path ?? pane.projectPath ?? null,
        };
        if (
          updated.model !== pane.model ||
          updated.agentType !== pane.agentType ||
          updated.role !== pane.role ||
          updated.title !== pane.title ||
          updated.isPrimary !== pane.isPrimary ||
          updated.projectPath !== pane.projectPath
        ) {
          changed = true;
        }
        return updated;
      });
      return changed ? next : prev;
    });
  }, [sessions, sessionMetaById]);

  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const addTerminalLog = useCallback((msg: string) => {
    setTerminalLogs((prev) => [...prev, msg]);
  }, []);

  const openFocusedRewind = useCallback(() => {
    sessionViewRefs.current.get(focusedSessionId)?.openRewind();
  }, [focusedSessionId]);

  const loadSessions = useCallback((projectPath?: string | null) => {
    void projectPath;
    fetch(`${API_BASE}/api/session-history`)
      .then((r) => r.json())
      .then((data) => setSessionHistory(data || null))
      .catch(console.error);
  }, []);

  const sessionHistoryHasRunning = React.useMemo(() => {
    if (!sessionHistory) return false;
    const standalone = Array.isArray(sessionHistory.standalone_sessions) ? sessionHistory.standalone_sessions : [];
    const projects = Array.isArray(sessionHistory.projects) ? sessionHistory.projects : [];
    return (
      standalone.some((session) => session.is_running) ||
      projects.some((project) => project.has_running || (project.sessions || []).some((session) => session.is_running))
    );
  }, [sessionHistory]);

  useEffect(() => {
    // Also poll in the parallel scenario (≥2 panes) so a backgrounded agent's
    // running indicator stays fresh even when the user is on a non-workspace
    // section (e.g. Personal) and no run was known when the poll last gated.
    const hasMultiplePanes = collectLeafNodes(paneRoot).length > 1;
    if (layout.activeSection !== 'workspace' && !sessionHistoryHasRunning && !hasMultiplePanes) return;
    const timer = window.setInterval(() => {
      loadSessions(currentProject?.path ?? null);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [currentProject?.path, layout.activeSection, loadSessions, sessionHistoryHasRunning, paneRoot]);

  // Slash command handler — delegates to focused session actions
  const handleSlashCommand = useCallback(async (command: string, args: string) => {
    const a = focusedActions;
    const arg = (args || '').trim().replace(/^(['"])(.*)\1$/, '$2');

    switch (command.toLowerCase()) {
      case 'new':
        newSessionRef.current();
        addTerminalLog('[Command] Creating a new Coding Agent session');
        break;
      case 'clear':
        a.clearSession();
        addTerminalLog('[命令] 已清除会话');
        break;
      case 'help':
        addTerminalLog('[Help] Commands: /new /clear /compact /rewind /context /help /model <model_id> /role <role_id> /project <path> /config /screenshot /skills');
        addTerminalLog('[帮助] 可用命令: /help /clear /compact /model /role /project /config /screenshot /skills');
        break;
      case 'compact':
        a.compactSession(false);
        addTerminalLog('[命令] 正在压缩对话上下文...');
        break;
      case 'rewind':
        openFocusedRewind();
        addTerminalLog('[Command] Choose a checkpoint to rewind');
        break;
      case 'context': {
        const usage = focusedSnapshot?.contextUsage;
        if (!usage) {
          addTerminalLog('[Context] Usage is still loading');
          break;
        }
        const parts = Object.entries(usage.breakdown || {})
          .map(([key, value]) => `${key}:${value}`)
          .join(' ');
        addTerminalLog(`[Context] ${usage.used_percent.toFixed(1)}% (${usage.used_tokens}/${usage.model_context}, ${usage.source}) ${parts}`);
        break;
      }
      case 'config':
        setShowSettings(true);
        addTerminalLog('[Command] Opened settings');
        break;
      case 'skills':
        layout.setSidebarCollapsed(false);
        layout.setActiveSection('skills');
        addTerminalLog('[Command] Opened Skills panel');
        break;
      case 'model': {
        if (!arg) {
          const available = models.map((m) => `${m.id}${m.name && m.name !== m.id ? ` (${m.name})` : ''}`).join(', ');
          addTerminalLog(available ? `[Model] Available models: ${available}` : '[Model] Models are still loading');
          break;
        }
        const target = models.find((m) => m.id === arg);
        if (!target) {
          const available = models.map((m) => m.id).join(', ');
          addTerminalLog(`[Model] Unknown model: ${arg}${available ? `. Available: ${available}` : ''}`);
          break;
        }
        setPaneRoot((prev) => mapPaneTree(prev, (pane) => (
          pane.sessionId === focusedSessionId ? { ...pane, model: arg } : pane
        )));
        a.switchModel(arg);
        loadSessions(currentProject?.path ?? null);
        addTerminalLog(`[Model] Switching focused session to ${arg}`);
        break;
      }
      case 'role': {
        if (!arg) {
          try {
            const res = await fetch(`${API_BASE}/api/roles`);
            const data = await res.json();
            const roles = (data.roles || []).map((r: { id: string; name?: string }) =>
              `${r.id}${r.name && r.name !== r.id ? ` (${r.name})` : ''}`
            );
            addTerminalLog(roles.length > 0 ? `[Role] Available roles: ${roles.join(', ')}` : '[Role] No roles found');
          } catch (err) {
            addTerminalLog(`[Role] Failed to load roles: ${err}`);
          }
          break;
        }
        const targetAgent = agentForRole(arg);
        layout.setActiveAgent(targetAgent);
        layout.setActiveSection(targetAgent === 'personal' ? 'personal' : 'workspace');
        setPaneRoot((prev) => {
          const leaf = findLeafById(prev, focusedLeafId);
          if (!leaf) return prev;
          return replaceNode(prev, focusedLeafId, {
            ...leaf,
            pane: {
              ...leaf.pane,
              agentType: targetAgent,
              role: arg,
              isPrimary: targetAgent === 'personal',
            },
          });
        });
        a.switchRole(arg);
        loadSessions(currentProject?.path ?? null);
        addTerminalLog(`[Role] Switching focused session to ${arg}`);
        break;
      }
      case 'project': {
        layout.setSidebarCollapsed(false);
        layout.setActiveSection('workspace');
        if (!arg) {
          setShowProjectModal(true);
          addTerminalLog('[Project] Choose a folder or create a project');
          break;
        }
        try {
          const res = await fetch(`${API_BASE}/api/projects/open`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: arg }),
          });
          const project = await res.json();
          if (project.error) {
            addTerminalLog(`[Project] Open failed: ${project.error}`);
            break;
          }
          setCurrentProject(project);

          const treeRes = await fetch(`${API_BASE}/api/projects/tree`);
          const tree = await treeRes.json().catch(() => ({}));
          setFileTree(tree.nodes || []);
          setExpandedPaths(new Set());
          setLoadingPaths(new Set());
          loadSessions(project.path);
          addTerminalLog(`[Project] Opened ${project.name || project.path}`);
        } catch (err) {
          addTerminalLog(`[Project] Open error: ${err}`);
        }
        break;
      }
      case 'screenshot':
        if (a) a.executeToolDirect('screenshot', {});
        addTerminalLog('[命令] 正在截图...');
        break;
      default:
        addTerminalLog(`[命令] 未知命令: /${command}`);
    }
  }, [
    addTerminalLog,
    focusedActions,
    focusedAgentType,
    focusedLeafId,
    focusedSessionId,
    focusedSnapshot?.contextUsage,
    currentProject?.path,
    layout,
    loadSessions,
    models,
    openFocusedRewind,
  ]);

  // Load models, roles, sessions
  useEffect(() => {
    let cancelled = false;
    setIsLoadingModels(true);

    const loadModels = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/models`);
        const data = await res.json();
        if (!cancelled) {
          const modelsList = data.models || [];
          setModels(modelsList);

          // Also load settings to get per-agent model preferences
          try {
            const settingsRes = await fetch(`${API_BASE}/api/settings`);
            const settingsData = await settingsRes.json();
            setAgentModels({
              personal: settingsData.personal_agent?.model || '',
              coding: settingsData.coding_agent?.model || '',
            });
          } catch {
            setAgentModels({ personal: '', coding: '' });
          }
        }
      } catch (err) {
        console.error('[App] Failed to load models:', err);
      }
    };

    const loadSettingsReadiness = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/settings`);
        const data = await res.json();
        if (!cancelled && !didPromptModelSetup.current && defaultProviderNeedsSetup(data)) {
          didPromptModelSetup.current = true;
          setShowSettings(true);
          addTerminalLog('[System] Agent model provider is not configured. Please update Settings first.');
        }
      } catch (err) {
        console.error('[App] Failed to check model settings:', err);
      }
    };

    const doLoad = async () => {
      await Promise.all([loadModels(), loadSettingsReadiness()]);
      if (!cancelled) setIsLoadingModels(false);
    };

    doLoad();
    loadSessions();
    loadCurrentProject();

    const retryTimer = setTimeout(() => {
      setModels((prevModels) => {
        if (prevModels.length === 0 && !cancelled) doLoad();
        return prevModels;
      });
    }, 2000);

    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleAgentChange = useCallback((agentType: AgentType) => {
    layout.setActiveAgent(agentType);
    // Switch section to match agent
    layout.setActiveSection(agentType === 'personal' ? 'personal' : 'workspace');
    // Update session pane role and model to match agent
    const defaultRole = roleForAgent(agentType);
    const newModel = agentModels[agentType] || '';
    setPaneRoot((prev) => {
      const leaf = findLeafById(prev, focusedLeafId);
      if (!leaf) return prev;
      const newPane = { ...leaf.pane, agentType, role: defaultRole, model: newModel };
      return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
    });
    addTerminalLog(`[系统] 已切换到 ${agentType === 'personal' ? 'Personal Agent' : 'Coding Agent'}`);
  }, [layout, focusedLeafId, addTerminalLog, agentModels]);

  const resolveAgentSessionClient = useCallback(async (
    agentType: AgentType,
    policy: 'canonical' | 'last_or_create' | 'new',
    projectPathOverride?: string | null,
  ): Promise<ResolvedSession> => {
    const projectPath = projectPathOverride ?? currentProject?.path;
    const res = await fetch(`${API_BASE}/api/sessions/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_type: agentType,
        policy,
        project_path: projectPath || undefined,
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || body.message || `Failed to resolve ${agentType} session`);
    }
    return res.json();
  }, [currentProject?.path]);

  const applyResolvedSessionToFocusedPane = useCallback((resolved: ResolvedSession) => {
    const agentType = normalizeAgentType(resolved.agent_type, resolved.role_id);
    layout.setActiveAgent(agentType);
    layout.setActiveSection(agentType === 'personal' ? 'personal' : 'workspace');
    lastFocusedLeafByAgent.current[agentType] = focusedLeafId;
    setPaneRoot((prev) => {
      const leaf = findLeafById(prev, focusedLeafId);
      if (!leaf) return prev;
      const newPane: SessionPane = {
        ...leaf.pane,
        sessionId: resolved.session_id,
        model: resolved.model_id || agentModels[agentType] || '',
        agentType,
        role: resolved.role_id || roleForAgent(agentType),
        title: resolved.title || undefined,
        isPrimary: !!resolved.is_primary,
        projectPath: resolved.project_path ?? null,
      };
      return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
    });
  }, [agentModels, focusedLeafId, layout]);

  // Switch to an agent without ever interrupting a running session: focus an
  // existing pane for that agent if one exists, otherwise open the resolved
  // session in a NEW split pane beside the focused one. The currently focused
  // (possibly running) pane is never replaced/unmounted — its WebSocket and
  // task keep going. Returns the agent's session id (existing or resolved).
  const openAgentSessionInPane = useCallback(async (
    agentType: AgentType,
    policy: 'canonical' | 'last_or_create' | 'new',
  ): Promise<string | null> => {
    layout.setActiveAgent(agentType);
    layout.setActiveSection(agentType === 'personal' ? 'personal' : 'workspace');

    const leaves = collectLeafNodes(paneRoot);
    const rememberedLeafId = lastFocusedLeafByAgent.current[agentType];
    const rememberedLeaf = rememberedLeafId ? findLeafById(paneRoot, rememberedLeafId) : null;
    const openLeaf = rememberedLeaf?.pane.agentType === agentType
      ? rememberedLeaf
      : leaves.find((entry) => entry.pane.agentType === agentType)?.node || null;

    if (openLeaf) {
      setFocusedLeafId(openLeaf.id);
      lastFocusedLeafByAgent.current[agentType] = openLeaf.id;
      return openLeaf.pane.sessionId;
    }

    let resolved: ResolvedSession;
    try {
      resolved = await resolveAgentSessionClient(agentType, policy);
    } catch (err) {
      console.error('[App] Failed to resolve agent session:', err);
      addTerminalLog(`[系统] Agent 切换失败: ${err instanceof Error ? err.message : String(err)}`);
      return null;
    }

    const model = resolved.model_id || agentModels[agentType] || agentModel;
    const newLeaf = createLeaf(agentType, model, resolved.session_id);
    newLeaf.pane.role = resolved.role_id || roleForAgent(agentType);
    newLeaf.pane.title = resolved.title || undefined;
    newLeaf.pane.isPrimary = !!resolved.is_primary;
    newLeaf.pane.projectPath = resolved.project_path ?? null;

    setPaneRoot((prev) => {
      const targetLeafId = findLeafById(prev, focusedLeafId)?.id ?? findFirstLeafId(prev);
      if (!targetLeafId) return newLeaf;
      const existingNode = findLeafById(prev, targetLeafId);
      if (!existingNode) return prev;
      const split: SplitNode = {
        type: 'split',
        id: nextNodeId(),
        direction: 'horizontal',
        children: [existingNode, newLeaf],
        sizes: [50, 50],
      };
      return replaceNode(prev, targetLeafId, split);
    });
    setFocusedLeafId(newLeaf.id);
    lastFocusedLeafByAgent.current[agentType] = newLeaf.id;
    loadSessions(currentProject?.path ?? null);
    addTerminalLog(`[系统] 已切换到 ${AGENT_LABEL[agentType]}`);
    return resolved.session_id;
  }, [addTerminalLog, agentModel, agentModels, currentProject?.path, focusedLeafId, layout, loadSessions, paneRoot, resolveAgentSessionClient]);

  const handleAgentNavigate = useCallback(async (agentType: AgentType) => {
    await openAgentSessionInPane(agentType, agentType === 'personal' ? 'canonical' : 'last_or_create');
  }, [openAgentSessionInPane]);

  const handleFocusLeaf = useCallback((leafId: string) => {
    setFocusedLeafId(leafId);
    const leaf = findLeafById(paneRoot, leafId);
    if (!leaf) return;
    lastFocusedLeafByAgent.current[leaf.pane.agentType] = leafId;
    layout.setActiveAgent(leaf.pane.agentType);
  }, [layout, paneRoot]);

  const saveAgentModelPreference = useCallback(async (agentType: string, modelId: string) => {
    try {
      const field = agentType === 'personal' ? 'personal_agent' : 'coding_agent';
      await fetch(`${API_BASE}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [field]: { model: modelId } }),
      });
    } catch (err) {
      console.error('[App] Failed to save agent model preference:', err);
    }
  }, []);

  const fetchProjectTreePath = useCallback(async (path = ''): Promise<FileNode[]> => {
    const url = path
      ? `${API_BASE}/api/projects/tree?path=${encodeURIComponent(path)}`
      : `${API_BASE}/api/projects/tree`;
    const res = await fetch(url);
    const data = await res.json();
    return data.nodes || [];
  }, []);

  const refreshProject = useCallback(async (options: { silent?: boolean } = {}) => {
    const silent = options.silent ?? false;
    setIsRefreshingProject(true);
    try {
      const res = await fetch(`${API_BASE}/api/projects/refresh`, { method: 'POST' });
      const data = await res.json();
      if (data.error) {
        if (!silent) addTerminalLog(`[Project] Refresh failed: ${data.error}`);
        if (!data.project && data.error === 'No current project') {
          setCurrentProject(null);
          setFileTree([]);
        }
        return;
      }
      if (data.project) {
        setCurrentProject(data.project);
      }
      let nextNodes: FileNode[] = data.nodes || [];
      for (const path of Array.from(expandedPaths)) {
        const node = findFileNode(nextNodes, path);
        if (
          node?.type === 'dir' &&
          node.has_children !== false &&
          !Object.prototype.hasOwnProperty.call(node, 'children')
        ) {
          const children = await fetchProjectTreePath(path);
          nextNodes = withDirectoryChildren(nextNodes, path, children);
        }
      }
      setFileTree(nextNodes);
      if (!silent) addTerminalLog('[Project] Refreshed project files');
    } catch (err) {
      console.error('[App] Failed to refresh project:', err);
      if (!silent) addTerminalLog(`[Project] Refresh error: ${err}`);
    } finally {
      setIsRefreshingProject(false);
    }
  }, [addTerminalLog, expandedPaths, fetchProjectTreePath]);

  const loadProjectTree = useCallback(async () => {
    await refreshProject({ silent: true });
  }, [refreshProject]);

  const loadDirectoryChildren = useCallback(async (path: string) => {
    setLoadingPaths((prev) => new Set(prev).add(path));
    try {
      const children = await fetchProjectTreePath(path);
      setFileTree((prev) => withDirectoryChildren(prev, path, children));
    } catch (err) {
      console.error('[App] Failed to load directory children:', err);
    } finally {
      setLoadingPaths((prev) => {
        const next = new Set(prev);
        next.delete(path);
        return next;
      });
    }
  }, [fetchProjectTreePath]);

  const scheduleProjectRefresh = useCallback(() => {
    if (!currentProject) return;
    if (projectRefreshTimerRef.current !== null) {
      window.clearTimeout(projectRefreshTimerRef.current);
    }
    projectRefreshTimerRef.current = window.setTimeout(() => {
      projectRefreshTimerRef.current = null;
      void refreshProject({ silent: true });
    }, 400);
  }, [currentProject, refreshProject]);

  useEffect(() => {
    return () => {
      if (projectRefreshTimerRef.current !== null) {
        window.clearTimeout(projectRefreshTimerRef.current);
      }
    };
  }, []);

  const loadCurrentProject = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/projects/current`);
      const data = await res.json();
      if (data && data.path && !data.error) {
        setCurrentProject(data);
        await loadProjectTree();
      }
    } catch (err) {
      console.error('[App] Failed to load current project:', err);
    }
  }, [loadProjectTree]);

  const handleOpenFolder = useCallback(async () => {
    const result = await window.electronAPI.selectFolder();
    if (result) {
      try {
        const res = await fetch(`${API_BASE}/api/projects/open`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: result }),
        });
        const project = await res.json();
        if (project.error) {
          console.error('[App] Open project failed:', project.error);
          return;
        }
        setCurrentProject(project);
        setExpandedPaths(new Set());
        setLoadingPaths(new Set());
        setFileTree(await fetchProjectTreePath());
        loadSessions(project.path);
        addTerminalLog(`[系统] 已打开项目: ${project.name}`);
      } catch (err) {
        console.error('[App] Open project error:', err);
      }
    }
  }, [fetchProjectTreePath, loadSessions, addTerminalLog]);

  const handleOpenProjectPath = useCallback(async (
    path: string,
    options: { touchRecent?: boolean; source?: 'manual' | 'focus-sync' } = {},
  ): Promise<ProjectInfo | null> => {
    if (!path) return null;
    const touchRecent = options.touchRecent ?? true;
    if ((options.source ?? 'manual') === 'manual') {
      manualProjectLockLeafRef.current = focusedLeafId;
    }
    try {
      const res = await fetch(`${API_BASE}/api/projects/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, touch_recent: touchRecent }),
      });
      const project = await res.json();
      if (project.error) {
        addTerminalLog(`[Project] Open failed: ${project.error}`);
        return null;
      }
      setCurrentProject(project);
      setExpandedPaths(new Set());
      setLoadingPaths(new Set());
      setFileTree(await fetchProjectTreePath());
      loadSessions(project.path);
      if (touchRecent) addTerminalLog(`[Project] Opened ${project.name || project.path}`);
      return project as ProjectInfo;
    } catch (err) {
      addTerminalLog(`[Project] Open error: ${err}`);
      return null;
    }
  }, [addTerminalLog, fetchProjectTreePath, focusedLeafId, loadSessions]);

  // File-tree zone follows the focused pane's project. Safe to flip the global
  // project here: backend execution is bound per-session, so this no longer
  // affects any running session — it is purely a UI/file-tree concern.
  const focusProjectSyncRef = useRef<string>('');
  useEffect(() => {
    const leaf = findLeafById(paneRoot, focusedLeafId);
    const paneProject = leaf?.pane.projectPath || '';
    if (!paneProject) return;
    if (manualProjectLockLeafRef.current && manualProjectLockLeafRef.current !== focusedLeafId) {
      manualProjectLockLeafRef.current = null;
    }
    if (manualProjectLockLeafRef.current === focusedLeafId) return;
    const paneKey = normalizeProjectPath(paneProject).toLowerCase();
    const currentKey = currentProject?.path ? normalizeProjectPath(currentProject.path).toLowerCase() : '';
    if (paneKey === currentKey || focusProjectSyncRef.current === paneKey) return;
    focusProjectSyncRef.current = paneKey;
    const targetLeafId = leaf.id;
    void handleOpenProjectPath(paneProject, { touchRecent: false, source: 'focus-sync' })
      .then((project) => {
        if (!project?.path) return;
        setPaneRoot((prev) => {
          const target = findLeafById(prev, targetLeafId);
          if (!target || target.pane.projectPath === project.path) return prev;
          return replaceNode(prev, targetLeafId, {
            ...target,
            pane: { ...target.pane, projectPath: project.path },
          });
        });
      })
      .finally(() => {
        if (focusProjectSyncRef.current === paneKey) focusProjectSyncRef.current = '';
      });
  }, [paneRoot, focusedLeafId, currentProject?.path, handleOpenProjectPath]);

  const handleProjectHistoryAction = useCallback(async (
    action: ProjectHistoryAction,
    project: SessionHistoryProject,
  ) => {
    const projectPath = project.path;
    const refreshHistory = () => loadSessions(currentProject?.path ?? null);

    const postJson = async (url: string, body: unknown) => {
      const res = await fetch(`${API_BASE}${url}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return res.json();
    };

    try {
      switch (action) {
        case 'pin':
        case 'unpin': {
          const data = await postJson('/api/projects/history/pin', {
            path: projectPath,
            pinned: action === 'pin',
          });
          if (data.error) {
            addTerminalLog(`[Project] Pin failed: ${apiErrorMessage(data.error)}`);
            return;
          }
          refreshHistory();
          addTerminalLog(`[Project] ${action === 'pin' ? 'Pinned' : 'Unpinned'} ${project.name}`);
          return;
        }
        case 'reveal': {
          const reveal = window.electronAPI?.revealPath;
          const open = window.electronAPI?.openPath;
          if (!reveal && !open) {
            addTerminalLog('[Project] Electron path actions unavailable');
            return;
          }
          const revealError = reveal ? await reveal(projectPath) : 'Reveal path unavailable';
          if (revealError && open) {
            const openError = await open(projectPath);
            if (openError) addTerminalLog(`[Project] Open project path failed: ${openError}`);
          } else if (revealError) {
            addTerminalLog(`[Project] Reveal project path failed: ${revealError}`);
          }
          return;
        }
        case 'worktree': {
          const defaultName = `${project.folder_name || project.name || 'project'}-worktree`;
          const name = window.prompt('创建永久工作树', defaultName);
          if (name === null) return;
          const data = await postJson('/api/projects/worktrees/persistent', {
            path: projectPath,
            name: name.trim() || defaultName,
          });
          if (data.error) {
            addTerminalLog(`[Project] Worktree failed: ${apiErrorMessage(data.error)}`);
            return;
          }
          if (data.project?.path) {
            setCurrentProject(data.project);
            setExpandedPaths(new Set());
            setLoadingPaths(new Set());
            setFileTree(await fetchProjectTreePath());
            loadSessions(data.project.path);
          } else {
            refreshHistory();
          }
          addTerminalLog(`[Project] Created persistent worktree: ${data.path || data.project?.path || project.name}`);
          return;
        }
        case 'rename': {
          setRenameProjectTarget(project);
          setRenameProjectError('');
          return;
        }
        case 'archive': {
          setConfirmProjectAction({ action: 'archive', project });
          setConfirmProjectError('');
          return;
        }
        case 'remove': {
          setConfirmProjectAction({ action: 'remove', project });
          setConfirmProjectError('');
          return;
        }
        default:
          return;
      }
    } catch (err) {
      addTerminalLog(`[Project] Action failed: ${err}`);
    }
  }, [addTerminalLog, currentProject?.path, fetchProjectTreePath, loadSessions]);

  const closeProjectRenameDialog = useCallback(() => {
    if (isRenamingProject) return;
    setRenameProjectTarget(null);
    setRenameProjectError('');
  }, [isRenamingProject]);

  const submitProjectRename = useCallback(async (name: string) => {
    if (!renameProjectTarget) return;
    setIsRenamingProject(true);
    setRenameProjectError('');
    try {
      const res = await fetch(`${API_BASE}/api/projects/history/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: renameProjectTarget.path, name }),
      });
      const data = await res.json();
      if (data.error) {
        setRenameProjectError(apiErrorMessage(data.error));
        return;
      }
      setRenameProjectTarget(null);
      loadSessions(currentProject?.path ?? null);
      addTerminalLog(`[Project] Renamed project to ${name}`);
    } catch (err) {
      setRenameProjectError(String(err));
    } finally {
      setIsRenamingProject(false);
    }
  }, [addTerminalLog, currentProject?.path, loadSessions, renameProjectTarget]);

  const closeProjectHistoryConfirm = useCallback(() => {
    if (isConfirmingProjectAction) return;
    setConfirmProjectAction(null);
    setConfirmProjectError('');
  }, [isConfirmingProjectAction]);

  const submitProjectHistoryConfirm = useCallback(async () => {
    if (!confirmProjectAction) return;
    setIsConfirmingProjectAction(true);
    setConfirmProjectError('');
    const { action, project } = confirmProjectAction;
    const url = action === 'archive'
      ? '/api/projects/history/archive-sessions'
      : '/api/projects/history/remove';

    try {
      const res = await fetch(`${API_BASE}${url}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: project.path }),
      });
      const data = await res.json();
      if (data.error) {
        setConfirmProjectError(apiErrorMessage(data.error));
        return;
      }
      setConfirmProjectAction(null);
      const isCurrentProjectAction = Boolean(
        currentProject?.path &&
        project.path &&
        normalizeProjectPath(currentProject.path).toLowerCase() === normalizeProjectPath(project.path).toLowerCase(),
      );
      if (action === 'remove' && isCurrentProjectAction) {
        try {
          await fetch(`${API_BASE}/api/projects/close`, { method: 'POST' });
        } catch (closeErr) {
          addTerminalLog(`[Project] Close after ${action} failed: ${closeErr}`);
        }
        setCurrentProject(null);
        setFileTree([]);
        setExpandedPaths(new Set());
        setLoadingPaths(new Set());
        loadSessions();
      } else {
        loadSessions(currentProject?.path ?? null);
      }
      if (action === 'archive') {
        addTerminalLog(`[Project] Archived ${data.archived_sessions ?? 0} sessions for ${project.name}`);
      } else {
        addTerminalLog(`[Project] Removed ${project.name} from history`);
      }
    } catch (err) {
      setConfirmProjectError(String(err));
    } finally {
      setIsConfirmingProjectAction(false);
    }
  }, [addTerminalLog, confirmProjectAction, currentProject?.path, loadSessions]);

  const handleCloseProject = useCallback(() => {
    fetch(`${API_BASE}/api/projects/close`, { method: 'POST' })
      .then(() => {
        setCurrentProject(null);
        setFileTree([]);
        setExpandedPaths(new Set());
        setLoadingPaths(new Set());
        loadSessions();
      })
      .catch(console.error);
  }, [loadSessions]);

  const handleTogglePath = useCallback((path: string) => {
    const willExpand = !expandedPaths.has(path);
    const node = findFileNode(fileTree, path);
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    if (
      willExpand &&
      node?.type === 'dir' &&
      node.has_children !== false &&
      !Object.prototype.hasOwnProperty.call(node, 'children')
    ) {
      void loadDirectoryChildren(path);
    }
  }, [expandedPaths, fileTree, loadDirectoryChildren]);

  // handleSelectFile → opens file in focused session's editor
  const revealWorkspaceEditor = useCallback(() => {
    layout.setRightPanelVisible(true);
    layout.setRightZone('workspace');
    setWorkspaceView('editor');
    requestAnimationFrame(() => {
      rightPanelRef.current?.expand?.();
    });
  }, [layout]);

  const openProjectFileInSession = useCallback((sessionId: string, file: PendingProjectFileOpen) => {
    const handle = sessionViewRefs.current.get(sessionId);
    if (!handle) return false;
    if (file.openToSide) {
      handle.openFile(file.path, file.content, file.language, { groupId: 'secondary' });
    } else {
      handle.openFile(file.path, file.content, file.language);
    }
    revealWorkspaceEditor();
    return true;
  }, [revealWorkspaceEditor]);

  useEffect(() => {
    const pending = pendingProjectFileOpenRef.current;
    if (!pending) return;
    if (openProjectFileInSession(pending.sessionId, pending)) {
      pendingProjectFileOpenRef.current = null;
    }
  }, [focusedSessionId, focusedAgentType, paneRoot, openProjectFileInSession]);

  const ensureCodingSessionForProject = useCallback(async (): Promise<string> => {
    if (focusedAgentType === 'coding') {
      return focusedSessionId;
    }
    // Focus an existing Coding pane, or open one in a new split pane — never
    // replaces the focused (possibly running Personal) pane.
    const sid = await openAgentSessionInPane('coding', 'last_or_create');
    return sid || focusedSessionId;
  }, [focusedAgentType, focusedSessionId, openAgentSessionInPane]);

  const handleSelectFile = useCallback(async (path: string, type: 'file' | 'dir', options: { openToSide?: boolean } = {}) => {
    if (type !== 'file' || !currentProject) return;
    try {
      const filePath = currentProject.path.replace(/\\/g, '/') + '/' + path;
      const res = await fetch(`${API_BASE}/api/file/read?path=${encodeURIComponent(filePath)}`);
      if (!res.ok) {
        addTerminalLog(`[Project] Failed to read file: ${path}`);
        return;
      }
      const data = await res.json();
      if (data.error) {
        addTerminalLog(`[Project] Read failed: ${data.error}`);
        return;
      }
      const content = data.content ?? '';
      const name = path.split('/').pop() || path;
      const language = getLangFromFilename(name);
      const sessionId = await ensureCodingSessionForProject();
      const pending: PendingProjectFileOpen = { sessionId, path, content, language, openToSide: options.openToSide };
      if (!openProjectFileInSession(sessionId, pending)) {
        pendingProjectFileOpenRef.current = pending;
        revealWorkspaceEditor();
      }
    } catch (err) {
      console.error('[App] Read file error:', err);
      addTerminalLog(`[Project] Read file error: ${err}`);
    }
  }, [addTerminalLog, currentProject, ensureCodingSessionForProject, openProjectFileInSession, revealWorkspaceEditor]);

  const closeProjectEditorPaths = useCallback((path: string, includeChildren = false) => {
    const matches: Array<{ groupId: string; fileId: string; path: string }> = [];
    for (const group of focusedSnapshot?.editorGroups || []) {
      for (const file of group.openFiles) {
        if (editorPathMatches(file.path, path, includeChildren)) {
          matches.push({ groupId: group.id, fileId: file.id, path: file.path });
        }
      }
    }
    for (const match of matches) {
      focusedActions.onCloseFileInEditor(match.groupId, match.fileId);
    }
    return matches;
  }, [focusedActions, focusedSnapshot?.editorGroups]);

  const handleElectronPathAction = useCallback(async (
    method: 'openPath' | 'revealPath' | 'openTerminal',
    absolutePath: string,
    label: string,
  ) => {
    if (!currentProject) return;
    if (!isProjectContained(currentProject, absolutePath)) {
      addTerminalLog(`[Project] Blocked path outside project: ${absolutePath}`);
      return;
    }
    const handler = window.electronAPI?.[method];
    if (!handler) {
      addTerminalLog(`[Project] Electron action unavailable: ${label}`);
      return;
    }
    try {
      const error = await handler(absolutePath);
      if (error) {
        addTerminalLog(`[Project] ${label} failed: ${error}`);
      }
    } catch (err) {
      addTerminalLog(`[Project] ${label} error: ${err}`);
    }
  }, [addTerminalLog, currentProject]);

  const handleCopyProjectPath = useCallback(async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      addTerminalLog(`[Project] Copied ${label}: ${text}`);
    } catch (err) {
      addTerminalLog(`[Project] Copy failed: ${err}`);
    }
  }, [addTerminalLog]);

  const handleRunProjectAction = useCallback(async (node: FileNode, action: 'run_file' | 'run_tests') => {
    if (!currentProject) return;
    try {
      const res = await fetch(`${API_BASE}/api/projects/actions/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: node.path, action }),
      });
      const data = await res.json();
      if (data.error && !data.command) {
        addTerminalLog(`[Run] ${apiErrorMessage(data.error)}`);
        return;
      }
      layout.setShowTerminal(true);
      requestAnimationFrame(() => terminalPanelRef.current?.expand());
      addTerminalLog(`[Run] ${data.command || action}`);
      if (data.output) addTerminalLog(String(data.output));
      if (data.error) addTerminalLog(`[Run] ${apiErrorMessage(data.error)}`);
    } catch (err) {
      addTerminalLog(`[Run] ${action} error: ${err}`);
    }
  }, [addTerminalLog, currentProject, layout]);

  const handleProjectFileAction = useCallback(async (action: FileTreeAction, node: FileNode) => {
    if (!currentProject) return;
    const absolutePath = projectAbsolutePath(currentProject, node.path);
    const terminalPath = projectParentPath(currentProject, node);

    switch (action) {
      case 'open':
        if (node.type === 'file') await handleSelectFile(node.path, 'file');
        else handleTogglePath(node.path);
        return;
      case 'open_side':
        if (node.type === 'file') await handleSelectFile(node.path, 'file', { openToSide: true });
        return;
      case 'open_external':
        await handleElectronPathAction('openPath', absolutePath, 'Open path');
        return;
      case 'reveal':
        await handleElectronPathAction('revealPath', absolutePath, 'Reveal path');
        return;
      case 'open_terminal':
        await handleElectronPathAction('openTerminal', terminalPath, 'Open terminal');
        return;
      case 'copy_path':
        await handleCopyProjectPath(absolutePath, 'path');
        return;
      case 'copy_relative_path':
        await handleCopyProjectPath(node.path, 'relative path');
        return;
      case 'toggle':
        if (node.type === 'dir') handleTogglePath(node.path);
        return;
      case 'rename': {
        const nextName = window.prompt('重命名', node.name)?.trim();
        if (!nextName || nextName === node.name) return;
        try {
          const res = await fetch(`${API_BASE}/api/projects/fs/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: node.path, new_name: nextName }),
          });
          const data = await res.json();
          if (data.error) {
            addTerminalLog(`[Project] Rename failed: ${apiErrorMessage(data.error)}`);
            return;
          }
          const matches = closeProjectEditorPaths(node.path, node.type === 'dir');
          setExpandedPaths((prev) => {
            const next = new Set(prev);
            for (const expanded of Array.from(next)) {
              if (editorPathMatches(expanded, node.path, true)) next.delete(expanded);
            }
            return next;
          });
          await refreshProject({ silent: true });
          addTerminalLog(`[Project] Renamed ${node.path} -> ${data.new_path || nextName}`);
          const firstMatch = matches[0];
          if (node.type === 'file' && firstMatch && data.new_path) {
            await handleSelectFile(data.new_path, 'file', { openToSide: firstMatch.groupId === 'secondary' });
          }
        } catch (err) {
          addTerminalLog(`[Project] Rename error: ${err}`);
        }
        return;
      }
      case 'delete': {
        if (!window.confirm(`删除 ${node.name}？文件会移入回收站。`)) return;
        try {
          const res = await fetch(`${API_BASE}/api/projects/fs/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: node.path }),
          });
          const data = await res.json();
          if (data.error) {
            addTerminalLog(`[Project] Delete failed: ${apiErrorMessage(data.error)}`);
            return;
          }
          closeProjectEditorPaths(node.path, node.type === 'dir');
          setExpandedPaths((prev) => {
            const next = new Set(prev);
            for (const expanded of Array.from(next)) {
              if (editorPathMatches(expanded, node.path, true)) next.delete(expanded);
            }
            return next;
          });
          await refreshProject({ silent: true });
          addTerminalLog(`[Project] Moved to recycle bin: ${node.path}`);
        } catch (err) {
          addTerminalLog(`[Project] Delete error: ${err}`);
        }
        return;
      }
      case 'run_file':
        await handleRunProjectAction(node, 'run_file');
        return;
      case 'run_tests':
        await handleRunProjectAction(node, 'run_tests');
        return;
      default:
        return;
    }
  }, [
    addTerminalLog,
    closeProjectEditorPaths,
    currentProject,
    handleCopyProjectPath,
    handleElectronPathAction,
    handleRunProjectAction,
    handleSelectFile,
    handleTogglePath,
    refreshProject,
  ]);

  const handleOpenFileFromPanel = useCallback((path: string) => {
    if (!currentProject) return;
    const normalized = (path || '').replace(/\\/g, '/');
    const projectRoot = (currentProject.path || '').replace(/\\/g, '/');
    const relative = normalized.startsWith(projectRoot + '/')
      ? normalized.slice(projectRoot.length + 1)
      : normalized;
    handleSelectFile(relative, 'file');
  }, [currentProject, handleSelectFile]);

  const handleOpenFileFromPanelWithLine = useCallback((path: string, _line?: number) => {
    handleOpenFileFromPanel(path);
  }, [handleOpenFileFromPanel]);

  const handleOpenPlanInWorkspace = useCallback(() => {
    revealWorkspaceEditor();
  }, [revealWorkspaceEditor]);

  const runAction = useCallback(async (runId: string, action: 'apply' | 'merge' | 'discard') => {
    try {
      const res = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: action === 'merge' ? JSON.stringify({}) : undefined,
      });
      const data = await res.json();
      if (data.error) {
        addTerminalLog(`[Run] ${action} failed: ${data.error}`);
        return;
      }
      addTerminalLog(`[Run] ${action} ${data.status || 'ok'}: ${runId}`);
      if (action === 'apply') loadProjectTree();
    } catch (err) {
      addTerminalLog(`[Run] ${action} error: ${err}`);
    }
  }, [addTerminalLog, loadProjectTree]);

  const openRunWorktree = useCallback(async (runId: string) => {
    try {
      const statusRes = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/worktree`);
      const status = await statusRes.json();
      const worktreePath = status.worktree_path;
      if (!worktreePath) {
        addTerminalLog(`[Run] no worktree to open for ${runId}`);
        return;
      }
      const res = await fetch(`${API_BASE}/api/projects/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: worktreePath }),
      });
      const project = await res.json();
      if (project.error) {
        addTerminalLog(`[Run] open worktree failed: ${project.error}`);
        return;
      }
      setCurrentProject(project);
      setExpandedPaths(new Set());
      setLoadingPaths(new Set());
      setFileTree(await fetchProjectTreePath());
      loadSessions(project.path);
      addTerminalLog(`[Run] opened worktree: ${worktreePath}`);
    } catch (err) {
      addTerminalLog(`[Run] open worktree error: ${err}`);
    }
  }, [addTerminalLog, fetchProjectTreePath, loadSessions]);

  // ---- Session pane management (tree-based) ----

  // Open a session from the Workspace panel. Never replaces a running pane:
  // if the session is already shown, just focus it; otherwise open it in a NEW
  // split pane next to the focused one. No global current-project flip — the
  // backend binds the project per-session, and the focus effect syncs the
  // file-tree zone.
  const switchSession = useCallback(async (newSessionId: string, projectPath?: string | null) => {
    const target = sessions.find((s) => s.id === newSessionId);
    const targetAgent = target ? normalizeAgentType(target.agent_type, target.role_id) : layout.activeAgent;
    const targetProjectPath = projectPath || target?.project_path || null;

    const existing = collectLeafNodes(paneRoot).find((entry) => entry.pane.sessionId === newSessionId);
    if (existing) {
      setFocusedLeafId(existing.leafId);
      lastFocusedLeafByAgent.current[existing.pane.agentType] = existing.leafId;
      layout.setActiveAgent(existing.pane.agentType);
      layout.setActiveSection(existing.pane.agentType === 'personal' ? 'personal' : 'workspace');
      return;
    }

    const model = target?.model_id || agentModels[targetAgent] || agentModel;
    const newLeaf = createLeaf(targetAgent, model, newSessionId);
    newLeaf.pane.role = target?.role_id || roleForAgent(targetAgent);
    newLeaf.pane.title = target?.title || undefined;
    newLeaf.pane.isPrimary = !!target?.is_primary;
    newLeaf.pane.projectPath = targetProjectPath;

    setPaneRoot((prev) => {
      const targetLeafId = findLeafById(prev, focusedLeafId)?.id ?? findFirstLeafId(prev);
      if (!targetLeafId) return newLeaf;
      const existingNode = findLeafById(prev, targetLeafId);
      if (!existingNode) return prev;
      const split: SplitNode = {
        type: 'split',
        id: nextNodeId(),
        direction: 'horizontal',
        children: [existingNode, newLeaf],
        sizes: [50, 50],
      };
      return replaceNode(prev, targetLeafId, split);
    });
    setFocusedLeafId(newLeaf.id);
    lastFocusedLeafByAgent.current[targetAgent] = newLeaf.id;
    layout.setActiveAgent(targetAgent);
    layout.setActiveSection(targetAgent === 'personal' ? 'personal' : 'workspace');
  }, [agentModel, agentModels, focusedLeafId, layout, paneRoot, sessions]);

  const stopSessionById = useCallback((sessionId: string) => {
    if (!sessionId) return;
    void fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/stop`, { method: 'POST' })
      .catch((err) => {
        console.error('[App] Failed to stop pane session:', err);
      });
  }, []);

  const newSession = useCallback(async () => {
    try {
      const resolved = await resolveAgentSessionClient('coding', 'new');
      applyResolvedSessionToFocusedPane(resolved);
      loadSessions(currentProject?.path ?? null);
      addTerminalLog('[系统] 已创建 Coding Agent session');
    } catch (err) {
      console.error('[App] Failed to create coding session:', err);
      const id = createDefaultSessionId('coding');
      setPaneRoot((prev) => {
        const leaf = findLeafById(prev, focusedLeafId);
        if (!leaf) return prev;
        const newPane: SessionPane = {
          ...leaf.pane,
          sessionId: id,
          model: agentModels.coding || agentModel,
          agentType: 'coding',
          role: roleForAgent('coding'),
          isPrimary: false,
        };
        return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
      });
    }
  }, [addTerminalLog, agentModel, agentModels.coding, applyResolvedSessionToFocusedPane, currentProject?.path, focusedLeafId, loadSessions, resolveAgentSessionClient]);

  const openNewSessionPane = useCallback(async (projectPathOverride?: string | null) => {
    const agentType: AgentType = 'coding';
    let sessionId = createDefaultSessionId(agentType);
    let model = agentModels.coding || agentModel;
    let role = roleForAgent(agentType);
    let title: string | undefined;
    const projectPath = projectPathOverride ?? currentProject?.path ?? null;

    try {
      const resolved = await resolveAgentSessionClient(agentType, 'new', projectPath);
      sessionId = resolved.session_id;
      model = resolved.model_id || model;
      role = resolved.role_id || role;
      title = resolved.title || undefined;
      loadSessions(projectPath);
      addTerminalLog('[System] Created Coding Agent session');
    } catch (err) {
      console.error('[App] Failed to create coding session:', err);
    }

    const newLeaf = createLeaf(agentType, model, sessionId);
    newLeaf.pane.role = role;
    newLeaf.pane.title = title;
    newLeaf.pane.isPrimary = false;
    newLeaf.pane.projectPath = projectPath ?? null;

    setPaneRoot((prev) => {
      const targetLeafId = findLeafById(prev, focusedLeafId)?.id ?? findFirstLeafId(prev);
      if (!targetLeafId) return newLeaf;
      const existing = findLeafById(prev, targetLeafId);
      if (!existing) return prev;
      const split: SplitNode = {
        type: 'split',
        id: nextNodeId(),
        direction: 'horizontal',
        children: [existing, newLeaf],
        sizes: [50, 50],
      };
      return replaceNode(prev, targetLeafId, split);
    });
    setFocusedLeafId(newLeaf.id);
    lastFocusedLeafByAgent.current.coding = newLeaf.id;
    layout.setActiveAgent(agentType);
    layout.setActiveSection('workspace');
  }, [
    addTerminalLog,
    agentModel,
    agentModels.coding,
    currentProject?.path,
    focusedLeafId,
    layout,
    loadSessions,
    resolveAgentSessionClient,
  ]);

  const handleNewProjectSession = useCallback(async (project: SessionHistoryProject) => {
    if (!project.path) return;
    // Resolve the new session bound to this project; the new pane becomes
    // focused and the focus effect syncs the file-tree zone. No pre-flip.
    await openNewSessionPane(project.path);
  }, [openNewSessionPane]);

  useEffect(() => {
    newSessionRef.current = openNewSessionPane;
  }, [openNewSessionPane]);

  const startFocusedSession = useCallback(() => {
    openNewSessionPane();
  }, [openNewSessionPane]);

  const replaceFocusedSessionAfterRemoval = useCallback(async (id: string) => {
    if (focusedSessionId !== id) return;
    const agentType: AgentType = layout.activeAgent === 'personal' ? 'personal' : 'coding';
    try {
      const resolved = await resolveAgentSessionClient(agentType, agentType === 'personal' ? 'canonical' : 'new');
      applyResolvedSessionToFocusedPane(resolved);
    } catch {
      const newId = createDefaultSessionId(agentType);
      setPaneRoot((prev) => {
        const leaf = findLeafById(prev, focusedLeafId);
        if (!leaf) return prev;
        const newPane: SessionPane = {
          ...leaf.pane,
          sessionId: newId,
          model: agentModels[agentType] || agentModel,
          agentType,
          role: roleForAgent(agentType),
          isPrimary: agentType === 'personal',
        };
        return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
      });
    }
  }, [
    focusedSessionId,
    focusedLeafId,
    agentModel,
    agentModels,
    layout.activeAgent,
    resolveAgentSessionClient,
    applyResolvedSessionToFocusedPane,
  ]);

  const archiveSession = useCallback(async (id: string) => {
    const res = await fetch(`${API_BASE}/api/sessions/${id}/archive`, { method: 'POST' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      addTerminalLog(`[Session] Archive failed: ${apiErrorMessage(data.detail || data.error || res.statusText)}`);
      return;
    }
    loadSessions();
    await replaceFocusedSessionAfterRemoval(id);
  }, [addTerminalLog, loadSessions, replaceFocusedSessionAfterRemoval]);

  const requestDeleteSession = useCallback((id: string) => {
    const existing = sessionMetaById[id];
    setDeleteSessionTarget(existing || {
      id,
      title: '',
      project_path: null,
      model_id: '',
      role_id: '',
      agent_type: 'coding',
      message_count: 0,
      is_primary: false,
      is_running: false,
      active_connections: 0,
      activity_state: 'idle',
    });
    setDeleteSessionError('');
  }, [sessionMetaById]);

  const closeSessionDeleteDialog = useCallback(() => {
    if (isDeletingSession) return;
    setDeleteSessionTarget(null);
    setDeleteSessionError('');
  }, [isDeletingSession]);

  const submitSessionDelete = useCallback(async () => {
    if (!deleteSessionTarget) return;
    const id = deleteSessionTarget.id;
    setIsDeletingSession(true);
    setDeleteSessionError('');
    try {
      const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setDeleteSessionError(apiErrorMessage(data.detail || data.error || res.statusText));
        return;
      }
      void Promise.allSettled([deleteSessionData(id), deleteDraft(id)]);
      setDeleteSessionTarget(null);
      loadSessions(currentProject?.path ?? null);
      await replaceFocusedSessionAfterRemoval(id);
    } catch (err) {
      setDeleteSessionError(String(err));
    } finally {
      setIsDeletingSession(false);
    }
  }, [currentProject?.path, deleteSessionTarget, loadSessions, replaceFocusedSessionAfterRemoval]);

  // Split a leaf into two panes (drag to edge)
  const handleSplitPane = useCallback(async (
    leafId: string,
    direction: 'horizontal' | 'vertical',
    options: SplitPaneOptions = {},
  ) => {
    const requestedAgent = options.agentType || (options.role ? agentForRole(options.role) : 'coding');
    if (requestedAgent === 'personal') {
      const existingPersonal = collectLeafNodes(paneRoot).find((entry) => entry.pane.agentType === 'personal');
      if (existingPersonal) {
        setFocusedLeafId(existingPersonal.leafId);
        return;
      }
    }
    const agentType: AgentType = requestedAgent === 'personal' ? 'personal' : 'coding';
    let resolvedOptions = options;
    if (agentType === 'coding' && !options.sessionId) {
      try {
        const resolved = await resolveAgentSessionClient('coding', 'new');
        resolvedOptions = {
          ...options,
          sessionId: resolved.session_id,
          model: resolved.model_id || options.model,
          role: resolved.role_id || options.role,
          agentType,
        };
        loadSessions(currentProject?.path ?? null);
        addTerminalLog('[系统] 已创建 Coding Agent session');
      } catch (err) {
        console.error('[App] Failed to create split coding session:', err);
        addTerminalLog(`[系统] 新建分屏 Coding session 失败，使用本地会话: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    const newLeaf = createLeaf(agentType, resolvedOptions.model || agentModels[agentType] || agentModel, resolvedOptions.sessionId);
    newLeaf.pane.role = resolvedOptions.role || roleForAgent(agentType);
    newLeaf.pane.isPrimary = agentType === 'personal';
    const placement = resolvedOptions.placement || 'after';

    setPaneRoot((prev) => {
      const existing = findLeafById(prev, leafId);
      if (!existing) return prev;
      const children = placement === 'before' ? [newLeaf, existing] : [existing, newLeaf];
      const split: SplitNode = {
        type: 'split',
        id: nextNodeId(),
        direction,
        children,
        sizes: [50, 50],
      };
      return replaceNode(prev, leafId, split);
    });
    setFocusedLeafId(newLeaf.id);
    lastFocusedLeafByAgent.current[agentType] = newLeaf.id;
  }, [addTerminalLog, agentModel, agentModels, currentProject?.path, loadSessions, paneRoot, resolveAgentSessionClient]);

  // Move a session from one leaf to another (drag to center of pane)
  const handleMoveSession = useCallback((fromLeafId: string, toLeafId: string) => {
    setPaneRoot((prev) => {
      const fromLeaf = findLeafById(prev, fromLeafId);
      const toLeaf = findLeafById(prev, toLeafId);
      if (!fromLeaf || !toLeaf || fromLeaf.id === toLeaf.id) return prev;
      // Swap the session data — keep the pane structure
      const fromSession = {
        sessionId: fromLeaf.pane.sessionId,
        model: fromLeaf.pane.model,
        agentType: fromLeaf.pane.agentType,
        role: fromLeaf.pane.role,
      };
      const toSession = {
        sessionId: toLeaf.pane.sessionId,
        model: toLeaf.pane.model,
        agentType: toLeaf.pane.agentType,
        role: toLeaf.pane.role,
      };
      let result = replaceNode(prev, fromLeafId, {
        ...fromLeaf,
        pane: { ...fromLeaf.pane, ...toSession },
      });
      result = replaceNode(result, toLeafId, {
        ...toLeaf,
        pane: { ...toLeaf.pane, ...fromSession },
      });
      return result;
    });
    setFocusedLeafId(toLeafId);
  }, []);

  const handlePaneModelChange = useCallback((leafId: string, modelId: string) => {
    if (!modelId) return;
    const targetLeaf = findLeafById(paneRoot, leafId);
    if (!targetLeaf) return;
    const targetSessionId = targetLeaf.pane.sessionId;
    const targetAgent = targetLeaf.pane.agentType || layout.activeAgent;

    setFocusedLeafId(leafId);
    lastFocusedLeafByAgent.current[targetAgent] = leafId;
    layout.setActiveAgent(targetAgent);

    setPaneRoot((prev) => mapPaneTree(prev, (pane) => (
      pane.sessionId === targetSessionId ? { ...pane, model: modelId } : pane
    )));

    const targetView = sessionViewRefs.current.get(targetSessionId);
    if (targetView?.switchModel) {
      targetView.switchModel(modelId);
    } else if (leafId === focusedLeafId) {
      focusedActions.switchModel(modelId);
    }
    loadSessions(currentProject?.path ?? null);
  }, [currentProject?.path, focusedActions, focusedLeafId, layout, loadSessions, paneRoot]);

  // Close a leaf pane
  const handleClosePane = useCallback((leafId: string) => {
    const closingLeaf = findLeafById(paneRoot, leafId);
    if (closingLeaf) {
      stopSessionById(closingLeaf.pane.sessionId);
    }

    setPaneRoot((prev) => {
      if (prev.type === 'leaf' && prev.id === leafId) {
        const removedPane = prev.pane;
        const newLeaf = createLeaf(layout.activeAgent, agentModel);
        sessionViewRefs.current.delete(removedPane.sessionId);
        setFocusedLeafId(newLeaf.id);
        setTeams((teams) => {
          const next = removePaneFromTeam(teams, removedPane.id);
          saveTeams(next);
          return next;
        });
        return newLeaf;
      }

      const result = removeLeaf(prev, leafId);
      if (!result) return prev;
      if (result.focusId) setFocusedLeafId(result.focusId);
      if (result.removedPane) {
        sessionViewRefs.current.delete(result.removedPane.sessionId);
        setTeams((teams) => {
          const next = removePaneFromTeam(teams, result.removedPane!.id);
          saveTeams(next);
          return next;
        });
      }
      return result.root;
    });
  }, [agentModel, layout.activeAgent, paneRoot, stopSessionById]);

  const handleSplitResize = useCallback((splitId: string, sizes: number[]) => {
    setPaneRoot((prev) => updateSplitSizes(prev, splitId, sizes));
  }, []);

  // ---- Team callbacks ----

  const handleJoinTeam = useCallback((paneId: string, teamId: string) => {
    setTeams((prev) => {
      const next = addPaneToTeam(prev, teamId, paneId);
      saveTeams(next);
      return next;
    });
    setPaneRoot((prev) => {
      const leaf = findLeafByPaneId(prev, paneId);
      if (!leaf) return prev;
      const updatedPane = { ...leaf.pane, teamId };
      return replaceNode(prev, leaf.id, { ...leaf, pane: updatedPane });
    });
  }, []);

  const handleCreateTeam = useCallback((name: string): Team => {
    const t = createTeam(name);
    setTeams((prev) => { const next = [...prev, t]; saveTeams(next); return next; });
    return t;
  }, []);

  const handleLeaveTeam = useCallback((paneId: string) => {
    setTeams((prev) => {
      const next = removePaneFromTeam(prev, paneId);
      saveTeams(next);
      return next;
    });
    setPaneRoot((prev) => {
      const leaf = findLeafByPaneId(prev, paneId);
      if (!leaf) return prev;
      const { teamId: _, ...rest } = leaf.pane;
      return replaceNode(prev, leaf.id, { ...leaf, pane: rest });
    });
  }, []);

  // ---- Snapshot callback from SessionView ----

  const handleSessionSnapshot = useCallback((snapshot: SessionSnapshot | null, actions: SessionActions) => {
    setFocusedSnapshot(snapshot);
    setFocusedActions(actions);
  }, []);

  // Sync suggestAgentSwitch from focused session to modal
  useEffect(() => {
    const suggestion = focusedSnapshot?.suggestAgentSwitch;
    if (suggestion && !localStorage.getItem('desktop-agent-never-suggest-switch')) {
      setSwitchSuggestion({
        from: (suggestion.from as AgentType) || 'personal',
        to: (suggestion.to as AgentType) || 'coding',
        reason: suggestion.reason || '',
      });
    }
  }, [focusedSnapshot?.suggestAgentSwitch]);

  // Electron menu events
  useEffect(() => {
    if (window.electronAPI?.onNewSession) {
      const handler = () => openNewSessionPane();
      const unsubscribe = window.electronAPI.onNewSession(handler);
      return () => { unsubscribe?.(); };
    }
  }, [openNewSessionPane]);

  // ---- Hotkeys ----
  useHotkeys('ctrl+\\, cmd+\\', (e) => {
    e.preventDefault();
    layout.toggleRightPanel();
  }, [layout]);

  useHotkeys('ctrl+j, cmd+j', (e) => {
    e.preventDefault();
    layout.toggleTerminal();
  }, [layout]);

  const handleMainLayoutChanged = useCallback((next: PanelLayout) => {
    if ((next.center ?? 0) > 1 && (next.right ?? 0) > 1) {
      layout.setMainLayout(next);
    }
  }, [layout]);

  const handleTerminalLayoutChanged = useCallback((next: PanelLayout) => {
    if ((next.conversation ?? 0) > 1 && (next.terminal ?? 0) > 1) {
      layout.setTerminalLayout(next);
    }
  }, [layout]);

  const handleResetLayout = useCallback(() => {
    layout.resetLayout();
    mainGroupRef.current?.setLayout(DEFAULT_MAIN_LAYOUT);
    centerGroupRef.current?.setLayout(DEFAULT_TERMINAL_LAYOUT);
    rightPanelRef.current?.expand();
    terminalPanelRef.current?.expand();
    setPaneRoot((prev) => resetSplitSizes(prev));
  }, [layout]);

  // ---- Derived: right panel props from focused snapshot ----
  const rpTools = focusedSnapshot?.toolCalls ?? [];
  const rpEdits = focusedSnapshot?.fileEdits ?? [];
  const rpRuns = focusedSnapshot?.runEvents ?? [];
  const rpArtifacts = focusedSnapshot?.artifacts ?? [];
  const rpIsRunning = focusedSnapshot?.isRunning ?? false;
  const rpLatestToolCall = focusedSnapshot?.latestToolCall ?? null;
  const rpEditorGroups = focusedSnapshot?.editorGroups ?? [{ id: 'main', activeFileId: null, openFiles: [] }];
  const rpActiveEditorGroup = focusedSnapshot?.activeEditorGroup ?? 'main';

  // ---- Render ----
  const isConnected = focusedSnapshot?.isConnected ?? false;
  const isRunning = rpIsRunning;

  return (
    <div className="h-screen flex flex-col bg-app text-fg overflow-hidden">
      {/* Title bar */}
      <div className="h-10 bg-surface border-b border-border flex items-center px-4 justify-between select-none app-drag app-titlebar">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-success' : 'bg-danger'}`} />
          <span className="text-sm font-semibold text-fg-secondary">Desktop Agent</span>
          <span className="text-xs text-fg-muted">/</span>
          <span className="text-xs font-medium text-fg truncate max-w-[320px]" title={focusedTitle}>
            {focusedTitle}
          </span>
          <span className="text-xs text-fg-muted ml-2">{isRunning ? '● Running' : '○ Ready'}</span>
        </div>
        <div className="flex items-center gap-2">
          <WindowControls
            showTerminal={layout.showTerminal}
            rightPanelVisible={layout.rightPanelVisible}
            onToggleTerminal={layout.toggleTerminal}
            onToggleRightPanel={layout.toggleRightPanel}
            onResetLayout={handleResetLayout}
          />
          <select
            value={focusedModel}
            title={`${layout.activeAgent === 'personal' ? 'Personal Agent' : 'Coding Agent'} 模型`}
            aria-label="切换模型"
            onChange={(e) => {
              handlePaneModelChange(focusedLeafId, e.target.value);
            }}
            className="text-xs text-fg-secondary bg-surface-hover/80 px-2 py-1 rounded border border-border outline-none cursor-pointer hover:bg-surface-hover transition-colors"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setShowSettings(true)}
            className="text-fg-secondary hover:text-fg p-1 rounded hover:bg-surface-hover transition-colors"
            title="设置"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Activity Bar */}
        <ActivityBar
          activeSection={layout.activeSection}
          activeAgent={layout.activeAgent}
          sidebarCollapsed={layout.sidebarCollapsed}
          onSectionChange={layout.setActiveSection}
          onAgentChange={handleAgentNavigate}
          onToggleSidebar={layout.toggleSidebar}
          personalRunning={agentRunningState.personal}
          codingRunning={agentRunningState.coding}
        />

        {/* Left sidebar */}
        {!layout.sidebarCollapsed && (
          <>
            <div className="min-w-0 shrink-0" style={{ width: sidebarWidth }}>
              <Sidebar
                activeSection={layout.activeSection}
                activeAgent={layout.activeAgent}
                onSectionChange={layout.setActiveSection}
                agentModel={focusedModel}
                onAgentChange={handleAgentNavigate}
                onOpenPersonalWorkspace={() => {
                  layout.setRightPanelVisible(true);
                  layout.setRightZone('workspace');
                }}
                onOpenSettings={() => setShowSettings(true)}
                onClear={focusedActions.clearSession}
                onExecuteTool={focusedActions.executeToolDirect}
                isConnected={isConnected}
                sessionHistory={sessionHistory}
                sessions={sessions}
                currentSession={focusedSessionId}
                onNewSession={startFocusedSession}
                onCompactSession={() => focusedActions.compactSession(false)}
                onRewindSession={openFocusedRewind}
                onSwitchSession={switchSession}
                onArchiveSession={archiveSession}
                onDeleteSession={requestDeleteSession}
                onOpenProject={(path) => { void handleOpenProjectPath(path, { touchRecent: false }); }}
                onProjectAction={handleProjectHistoryAction}
                onNewProjectSession={handleNewProjectSession}
                currentProjectPath={currentProject?.path ?? null}
                currentProject={currentProject}
                fileTree={fileTree}
                expandedPaths={expandedPaths}
                loadingPaths={loadingPaths}
                onTogglePath={handleTogglePath}
                onSelectFile={handleSelectFile}
                onFileAction={handleProjectFileAction}
                onOpenFolder={handleOpenFolder}
                onOpenProjectModal={() => setShowProjectModal(true)}
                onCloseProject={handleCloseProject}
                onRefreshTree={refreshProject}
                isRefreshingProject={isRefreshingProject}
              />
            </div>
            <div
              role="separator"
              aria-label="Resize left sidebar"
              aria-orientation="vertical"
              aria-valuemin={MIN_SIDEBAR_WIDTH}
              aria-valuemax={MAX_SIDEBAR_WIDTH}
              aria-valuenow={Math.round(sidebarWidth)}
              title="Resize left sidebar"
              tabIndex={0}
              onPointerDown={handleSidebarResizeStart}
              onKeyDown={handleSidebarResizeKeyDown}
              onDoubleClick={() => layout.setSidebarWidth(DEFAULT_SIDEBAR_WIDTH)}
              className="group flex h-full w-2 shrink-0 cursor-col-resize items-stretch justify-center bg-surface transition-colors hover:bg-accent/5"
            >
              <div className="h-full w-px bg-border transition-colors group-hover:bg-accent/60" />
            </div>
            <ProjectModal
              isOpen={showProjectModal}
              onClose={() => setShowProjectModal(false)}
              onProjectCreated={async (project) => {
                setCurrentProject(project);
                setExpandedPaths(new Set());
                setLoadingPaths(new Set());
                setFileTree(await fetchProjectTreePath());
                loadSessions(project.path);
                setShowProjectModal(false);
                addTerminalLog(`[系统] 已创建项目: ${project.name}`);
              }}
            />
            <ProjectRenameDialog
              isOpen={!!renameProjectTarget}
              initialName={renameProjectTarget?.display_name || renameProjectTarget?.name || ''}
              projectPath={renameProjectTarget?.path}
              loading={isRenamingProject}
              error={renameProjectError}
              onClose={closeProjectRenameDialog}
              onSubmit={submitProjectRename}
            />
            <ProjectHistoryConfirmDialog
              isOpen={!!confirmProjectAction}
              action={confirmProjectAction?.action || 'archive'}
              project={confirmProjectAction?.project || null}
              loading={isConfirmingProjectAction}
              error={confirmProjectError}
              onClose={closeProjectHistoryConfirm}
              onConfirm={submitProjectHistoryConfirm}
            />
            <SessionDeleteConfirmDialog
              isOpen={!!deleteSessionTarget}
              session={deleteSessionTarget}
              loading={isDeletingSession}
              error={deleteSessionError}
              onClose={closeSessionDeleteDialog}
              onConfirm={submitSessionDelete}
            />
          </>
        )}

        <SettingsModal
          isOpen={showSettings}
          onClose={() => setShowSettings(false)}
          models={models}
          currentModel={focusedModel}
          onSettingsChanged={async () => {
            try {
              const res = await fetch(`${API_BASE}/api/models`);
              const data = await res.json();
              const modelsList = data.models || [];
              setModels(modelsList);

              // Re-fetch per-agent model settings
              try {
                const settingsRes = await fetch(`${API_BASE}/api/settings`);
                const settingsData = await settingsRes.json();
                setAgentModels({
                  personal: settingsData.personal_agent?.model || '',
                  coding: settingsData.coding_agent?.model || '',
                });
              } catch {
                setAgentModels({ personal: '', coding: '' });
              }
            } catch (err) {
              console.error('[App] Failed to refresh models after settings change:', err);
            }
          }}
        />

        <SwitchAgentModal
          isOpen={!!switchSuggestion}
          from={switchSuggestion?.from || 'personal'}
          to={switchSuggestion?.to || 'coding'}
          reason={switchSuggestion?.reason || ''}
          onSwitch={() => {
            if (switchSuggestion) {
              void handleAgentNavigate(switchSuggestion.to);
            }
            setSwitchSuggestion(null);
          }}
          onDismiss={() => setSwitchSuggestion(null)}
          onNeverAsk={() => {
            localStorage.setItem('desktop-agent-never-suggest-switch', 'true');
            setSwitchSuggestion(null);
          }}
        />

        {/* Center + right panel — horizontal Group */}
        <Group
          id="desktop-agent-main-layout"
          groupRef={mainGroupRef}
          orientation="horizontal"
          defaultLayout={layout.mainLayout}
          onLayoutChanged={handleMainLayoutChanged}
          className="flex-1 min-w-0"
          resizeTargetMinimumSize={RESIZE_TARGET_MINIMUM_SIZE}
        >
          {/* Center area */}
          <Panel id="center" minSize="360px">
            <div className="flex flex-col h-full">
              {/* Vertical Group: Pane tree + Terminal */}
              <Group
                id="desktop-agent-center-layout"
                groupRef={centerGroupRef}
                orientation="vertical"
                defaultLayout={layout.terminalLayout}
                onLayoutChanged={handleTerminalLayoutChanged}
                className="flex-1 min-h-0"
                resizeTargetMinimumSize={RESIZE_TARGET_MINIMUM_SIZE}
              >
                <Panel id="conversation" minSize="280px">
                  <PaneRenderer
                    node={paneRoot}
                    focusedLeafId={focusedLeafId}
                    onFocus={handleFocusLeaf}
                    onClosePane={handleClosePane}
                    onSplit={handleSplitPane}
                    onMoveSession={handleMoveSession}
                    onSplitResize={handleSplitResize}
                    teams={teams}
                    onJoinTeam={handleJoinTeam}
                    onCreateTeam={handleCreateTeam}
                    onLeaveTeam={handleLeaveTeam}
                    sessionViewRefs={sessionViewRefs}
                    currentProject={currentProject}
                    currentModel={focusedModel}
                    currentAgentType={focusedAgentType}
                    currentRole={roleForAgent(focusedAgentType)}
                    models={models}
                    sessionMetaById={sessionMetaById}
                    onModelChange={handlePaneModelChange}
                    onSnapshot={handleSessionSnapshot}
                    onCommand={handleSlashCommand}
                    runAction={runAction}
                    openRunWorktree={openRunWorktree}
                    handleOpenFileFromPanel={handleOpenFileFromPanel}
                    handleOpenFileFromPanelWithLine={handleOpenFileFromPanelWithLine}
                    onOpenPlanInWorkspace={handleOpenPlanInWorkspace}
                    onProjectFileEdit={scheduleProjectRefresh}
                  />
                </Panel>

                {/* Terminal (shared) */}
                <Separator className="h-px bg-border hover:bg-accent/50 active:bg-accent/70 transition-colors cursor-row-resize" />
                <Panel
                  id="terminal"
                  panelRef={terminalPanelRef}
                  collapsible
                  collapsedSize={0}
                  minSize="96px"
                  maxSize="70%"
                  onResize={(size) => {
                    if (size.asPercentage <= 1) layout.setShowTerminal(false);
                    else if (!layout.showTerminal) layout.setShowTerminal(true);
                  }}
                >
                  <div className="relative h-full">
                    {layout.showTerminal && (
                      <>
                        <button
                          type="button"
                          onClick={() => terminalPanelRef.current?.collapse()}
                          className="absolute -top-4 left-1/2 -translate-x-1/2 w-8 h-4 bg-surface border border-border border-b-0 rounded-t-md flex items-start justify-center hover:bg-surface-hover transition-colors z-10"
                          title="Collapse terminal (Ctrl+J)"
                        >
                          <ChevronDown className="w-3 h-3 text-fg-muted mt-0.5" />
                        </button>
                        <TerminalPanel logs={terminalLogs} />
                      </>
                    )}
                  </div>
                </Panel>
              </Group>

              {!layout.showTerminal && (
                <button
                  type="button"
                  onClick={() => terminalPanelRef.current?.expand()}
                  className="h-5 bg-surface border-t border-border flex items-center justify-center hover:bg-surface-hover transition-colors shrink-0 group"
                  title="Expand terminal (Ctrl+J)"
                >
                  <ChevronUp className="w-3 h-3 text-fg-muted group-hover:text-fg-secondary" />
                </button>
              )}
            </div>
          </Panel>

          {/* Right panel */}
          <Separator className="bg-border hover:bg-accent/50 active:bg-accent/70 transition-colors cursor-col-resize" style={{ width: 3 }} />
          <Panel
            id="right"
            panelRef={rightPanelRef}
            minSize="300px"
            maxSize="70%"
            collapsible collapsedSize={0}
            onResize={(size) => {
              if (size.asPercentage <= 1) layout.setRightPanelVisible(false);
              else if (!layout.rightPanelVisible) layout.setRightPanelVisible(true);
            }}
          >
            <div className="bg-surface flex flex-col h-full min-w-0">
              {/* Two-zone tab bar */}
              <div className="flex border-b border-border shrink-0">
                <button
                  type="button"
                  onClick={() => layout.setRightZone('workspace')}
                  className={`flex items-center gap-1.5 shrink-0 px-3 py-2 text-xs font-medium ${
                    layout.rightZone === 'workspace' ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:text-fg'
                  }`}
                >
                  <Monitor className="w-3.5 h-3.5" />
                  工作区
                </button>
                <button
                  type="button"
                  onClick={() => layout.setRightZone('activity')}
                  className={`flex items-center gap-1.5 shrink-0 px-3 py-2 text-xs font-medium ${
                    layout.rightZone === 'activity' ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:text-fg'
                  }`}
                >
                  <Activity className="w-3.5 h-3.5" />
                  活动
                </button>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden">
                {layout.rightZone === 'workspace' && focusedAgentType === 'personal' && (
                  <PersonalWorkspacePanel />
                )}
                {layout.rightZone === 'workspace' && focusedAgentType !== 'personal' && (
                  <FocusedDataProvider value={focusedSnapshot}>
                    <FocusedActionsProvider value={focusedActions}>
                      <WorkspacePanel
                        activeView={workspaceView}
                        onActiveViewChange={setWorkspaceView}
                        editorGroups={rpEditorGroups}
                        activeEditorGroup={rpActiveEditorGroup}
                        projectName={currentProject?.name || '未打开项目'}
                        onSelectFile={focusedActions.onSelectFileInEditor}
                        onCloseFile={focusedActions.onCloseFileInEditor}
                        onMoveToGroup={() => {}}
                        onSplitEditor={() => {}}
                        onCloseSplit={() => {}}
                        onSetActiveGroup={() => {}}
                        onFileContentChange={focusedActions.onFileContentChange}
                        onSaveFile={focusedActions.onSaveFile}
                        artifacts={rpArtifacts}
                        isRunning={rpIsRunning}
                        latestToolCall={rpLatestToolCall}
                        previewUrl={previewUrl}
                        onAnnotate={(a) => {
                          const msg = `[标注] [${a.url || '预览页面'}] 区域(${a.rect.x}%,${a.rect.y}%,${a.rect.w}%x${a.rect.h}%): ${a.note}`;
                          focusedActions.sendMessage(msg, a.base64);
                        }}
                      />
                    </FocusedActionsProvider>
                  </FocusedDataProvider>
                )}
                {layout.rightZone === 'activity' && (
                  <FocusedDataProvider value={focusedSnapshot}>
                    <FocusedActionsProvider value={focusedActions}>
                      <ActivityPanel
                        toolCalls={rpTools}
                        fileEdits={rpEdits}
                        runEvents={rpRuns}
                        onOpenFileFromChanges={focusedActions.handleOpenFileFromPanel}
                        onOpenFileFromTests={focusedActions.handleOpenFileFromPanel}
                        onOpenFileFromProblems={focusedActions.handleOpenFileFromPanelWithLine}
                        onOpenWorktree={focusedActions.openRunWorktree}
                        onApplyRun={(runId) => focusedActions.runAction(runId, 'apply')}
                        onMergeRun={(runId) => focusedActions.runAction(runId, 'merge')}
                        onDiscardRun={(runId) => focusedActions.runAction(runId, 'discard')}
                      />
                    </FocusedActionsProvider>
                  </FocusedDataProvider>
                )}
              </div>
            </div>
          </Panel>
        </Group>

        {/* Right panel expand strip */}
        {!layout.rightPanelVisible && (
          <div className="w-9 flex-shrink-0 border-l border-border bg-surface flex flex-col items-center py-2 gap-3">
            <button
              type="button"
              onClick={() => layout.setRightPanelVisible(true)}
              className="w-6 h-6 rounded flex items-center justify-center text-fg-muted hover:text-fg hover:bg-surface-hover transition-colors"
              title="Expand panel (Ctrl+\)"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => { layout.setRightZone('workspace'); layout.setRightPanelVisible(true); }}
              className={`w-6 h-6 rounded flex items-center justify-center text-xs ${layout.rightZone === 'workspace' ? 'text-fg bg-surface-alt' : 'text-fg-muted hover:text-fg hover:bg-surface-hover'} transition-colors`}
              title="工作区"
            >W</button>
            <button
              type="button"
              onClick={() => { layout.setRightZone('activity'); layout.setRightPanelVisible(true); }}
              className={`w-6 h-6 rounded flex items-center justify-center text-xs ${layout.rightZone === 'activity' ? 'text-fg bg-surface-alt' : 'text-fg-muted hover:text-fg hover:bg-surface-hover'} transition-colors`}
              title="活动"
            >A</button>
          </div>
        )}
      </div>
    </div>
  );
}
