import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { Panel, Group, Separator } from 'react-resizable-panels';
import type { GroupImperativeHandle, PanelImperativeHandle } from 'react-resizable-panels';
import { AnimatePresence, motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { Sidebar } from './components/Sidebar';
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
import { ModelInfo, ProjectInfo, FileNode, SettingsResponse, type AgentType } from './types';
import { API_BASE } from './config';
import {
  DEFAULT_MAIN_LAYOUT,
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
import { SettingsModal } from './components/SettingsModal';
import { ActivityBar } from './components/ActivityBar';
import { WindowControls } from './components/WindowControls';

interface SessionListItem {
  id: string;
  title?: string;
  project_path?: string;
  model_id: string;
  role_id?: string;
  agent_type?: AgentType;
  message_count: number;
  updated_at?: number;
  is_primary?: boolean;
}

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
}

type SplitPlacement = 'before' | 'after';

interface SplitPaneOptions {
  sessionId?: string;
  placement?: SplitPlacement;
  model?: string;
  role?: string;
  agentType?: AgentType;
}

function defaultProviderNeedsSetup(settings: SettingsResponse | null): boolean {
  if (!settings?.settings || !settings.providers) return false;
  const defaultProvider = settings.providers[settings.settings.default_provider];
  if (!defaultProvider) return true;
  if (typeof defaultProvider.api_key_configured === 'boolean') {
    return !defaultProvider.api_key_configured;
  }
  const masked = defaultProvider.api_key_masked || '';
  return !masked || (masked.startsWith('${') && masked.endsWith('}'));
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
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [showSettings, setShowSettings] = useState(false);

  const [currentProject, setCurrentProject] = useState<ProjectInfo | null>(null);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [showProjectModal, setShowProjectModal] = useState(false);
  const [isRefreshingProject, setIsRefreshingProject] = useState(false);

  const layout = useLayoutState();
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
        };
        if (
          updated.model !== pane.model ||
          updated.agentType !== pane.agentType ||
          updated.role !== pane.role ||
          updated.title !== pane.title ||
          updated.isPrimary !== pane.isPrimary
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
    const url = projectPath
      ? `${API_BASE}/api/sessions?project_path=${encodeURIComponent(projectPath)}`
      : `${API_BASE}/api/sessions`;
    fetch(url)
      .then((r) => r.json())
      .then((data) => setSessions(data.sessions || []))
      .catch(console.error);
  }, []);

  // Slash command handler — delegates to focused session actions
  const handleSlashCommand = useCallback(async (command: string, args: string) => {
    const a = focusedActions;
    const arg = (args || '').trim().replace(/^(['"])(.*)\1$/, '$2');

    switch (command.toLowerCase()) {
      case 'new':
        if (focusedAgentType === 'personal') {
          a.clearSession();
          addTerminalLog('[Command] Started a fresh Personal Agent session');
        } else {
          newSessionRef.current();
          addTerminalLog('[Command] Creating a new Coding Agent session');
        }
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
        setSessions((prev) => prev.map((session) => (
          session.id === focusedSessionId ? { ...session, model_id: arg } : session
        )));
        a.switchModel(arg);
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
        layout.setActiveSection(targetAgent === 'personal' ? 'personal' : 'project');
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
        setSessions((prev) => prev.map((session) => (
          session.id === focusedSessionId
            ? { ...session, role_id: arg, agent_type: targetAgent, is_primary: targetAgent === 'personal' }
            : session
        )));
        a.switchRole(arg);
        addTerminalLog(`[Role] Switching focused session to ${arg}`);
        break;
      }
      case 'project': {
        layout.setSidebarCollapsed(false);
        layout.setActiveSection('project');
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

          const [treeRes, sessionsRes] = await Promise.all([
            fetch(`${API_BASE}/api/projects/tree`),
            fetch(`${API_BASE}/api/sessions?project_path=${encodeURIComponent(project.path)}`),
          ]);
          const tree = await treeRes.json().catch(() => ({}));
          const sessionData = await sessionsRes.json().catch(() => ({}));
          setFileTree(tree.nodes || []);
          setExpandedPaths(new Set());
          setLoadingPaths(new Set());
          setSessions(sessionData.sessions || []);
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
    layout,
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
          const defaultModel = data.default || modelsList[0]?.id || '';

          // Also load settings to get per-agent model preferences
          try {
            const settingsRes = await fetch(`${API_BASE}/api/settings`);
            const settingsData = await settingsRes.json();
            setAgentModels({
              personal: settingsData.personal_agent?.model || defaultModel,
              coding: settingsData.coding_agent?.model || defaultModel,
            });
          } catch {
            setAgentModels({ personal: defaultModel, coding: defaultModel });
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
          addTerminalLog('[系统] 默认模型尚未配置 API Key，请先在设置中填写。');
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
    layout.setActiveSection(agentType === 'personal' ? 'personal' : 'project');
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
  ): Promise<ResolvedSession> => {
    const res = await fetch(`${API_BASE}/api/sessions/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_type: agentType,
        policy,
        project_path: currentProject?.path || undefined,
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
    layout.setActiveSection(agentType === 'personal' ? 'personal' : 'project');
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
      };
      return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
    });
  }, [agentModels, focusedLeafId, layout]);

  const handleAgentNavigate = useCallback(async (agentType: AgentType) => {
    layout.setActiveAgent(agentType);
    layout.setActiveSection(agentType === 'personal' ? 'personal' : 'project');

    const leaves = collectLeafNodes(paneRoot);
    const rememberedLeafId = lastFocusedLeafByAgent.current[agentType];
    const rememberedLeaf = rememberedLeafId ? findLeafById(paneRoot, rememberedLeafId) : null;
    const openLeaf = rememberedLeaf?.pane.agentType === agentType
      ? rememberedLeaf
      : leaves.find((entry) => entry.pane.agentType === agentType)?.node || null;

    if (openLeaf) {
      setFocusedLeafId(openLeaf.id);
      lastFocusedLeafByAgent.current[agentType] = openLeaf.id;
      return;
    }

    try {
      const resolved = await resolveAgentSessionClient(
        agentType,
        agentType === 'personal' ? 'canonical' : 'last_or_create',
      );
      applyResolvedSessionToFocusedPane(resolved);
      loadSessions(currentProject?.path ?? null);
      addTerminalLog(`[系统] 已切换到 ${AGENT_LABEL[agentType]}`);
    } catch (err) {
      console.error('[App] Failed to navigate agent:', err);
      addTerminalLog(`[系统] Agent 切换失败: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [addTerminalLog, applyResolvedSessionToFocusedPane, currentProject?.path, layout, loadSessions, paneRoot, resolveAgentSessionClient]);

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
  }, []);

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
    handle.openFile(file.path, file.content, file.language);
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

    const leaves = collectLeafNodes(paneRoot);
    const rememberedLeafId = lastFocusedLeafByAgent.current.coding;
    const rememberedLeaf = rememberedLeafId ? findLeafById(paneRoot, rememberedLeafId) : null;
    const codingLeaf = rememberedLeaf?.pane.agentType === 'coding'
      ? rememberedLeaf
      : leaves.find((entry) => entry.pane.agentType === 'coding')?.node || null;

    layout.setActiveAgent('coding');
    layout.setActiveSection('project');
    if (codingLeaf) {
      setFocusedLeafId(codingLeaf.id);
      lastFocusedLeafByAgent.current.coding = codingLeaf.id;
      return codingLeaf.pane.sessionId;
    }

    const resolved = await resolveAgentSessionClient('coding', 'last_or_create');
    applyResolvedSessionToFocusedPane(resolved);
    loadSessions(currentProject?.path ?? null);
    addTerminalLog(`[ç³»ç»Ÿ] å·²åˆ‡æ¢åˆ° ${AGENT_LABEL.coding}`);
    return resolved.session_id;
  }, [
    addTerminalLog,
    applyResolvedSessionToFocusedPane,
    currentProject?.path,
    focusedAgentType,
    focusedSessionId,
    layout,
    loadSessions,
    paneRoot,
    resolveAgentSessionClient,
  ]);

  const handleSelectFile = useCallback(async (path: string, type: 'file' | 'dir') => {
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
      const pending: PendingProjectFileOpen = { sessionId, path, content, language };
      if (!openProjectFileInSession(sessionId, pending)) {
        pendingProjectFileOpenRef.current = pending;
        revealWorkspaceEditor();
      }
    } catch (err) {
      console.error('[App] Read file error:', err);
      addTerminalLog(`[Project] Read file error: ${err}`);
    }
  }, [addTerminalLog, currentProject, ensureCodingSessionForProject, openProjectFileInSession, revealWorkspaceEditor]);

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
      addTerminalLog(`[Run] opened worktree: ${worktreePath}`);
    } catch (err) {
      addTerminalLog(`[Run] open worktree error: ${err}`);
    }
  }, [addTerminalLog, fetchProjectTreePath]);

  // ---- Session pane management (tree-based) ----

  const switchSession = useCallback((newSessionId: string) => {
    const target = sessions.find((s) => s.id === newSessionId);
    const targetAgent = target ? normalizeAgentType(target.agent_type, target.role_id) : layout.activeAgent;
    layout.setActiveAgent(targetAgent);
    if (targetAgent === 'personal') {
      const existingPersonal = collectLeafNodes(paneRoot).find((entry) => entry.pane.agentType === 'personal');
      if (existingPersonal) {
        setFocusedLeafId(existingPersonal.leafId);
        lastFocusedLeafByAgent.current.personal = existingPersonal.leafId;
        return;
      }
    }
    setPaneRoot((prev) => {
      const leaf = findLeafById(prev, focusedLeafId);
      if (!leaf) return prev;
      const newPane: SessionPane = {
        ...leaf.pane,
        sessionId: newSessionId,
        model: target?.model_id || agentModels[targetAgent] || agentModel,
        agentType: targetAgent,
        role: target?.role_id || roleForAgent(targetAgent),
        title: target?.title || undefined,
        isPrimary: !!target?.is_primary,
      };
      return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
    });
  }, [focusedLeafId, sessions, agentModel, agentModels, layout, paneRoot]);

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

  useEffect(() => {
    newSessionRef.current = newSession;
  }, [newSession]);

  const startFocusedSession = useCallback(() => {
    if (focusedAgentType === 'personal') {
      focusedActions.clearSession();
      addTerminalLog('[Command] Started a fresh Personal Agent session');
      return;
    }
    newSession();
  }, [focusedActions, focusedAgentType, newSession, addTerminalLog]);

  const deleteSession = useCallback(async (id: string) => {
    await fetch(`${API_BASE}/api/sessions/${id}`, { method: 'DELETE' });
    loadSessions();
    // If the deleted session is the focused one, create a new one in that leaf
    if (focusedSessionId === id) {
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
    }
  }, [
    focusedSessionId,
    focusedLeafId,
    agentModel,
    agentModels,
    layout.activeAgent,
    loadSessions,
    resolveAgentSessionClient,
    applyResolvedSessionToFocusedPane,
  ]);

  // Split a leaf into two panes (drag to edge)
  const handleSplitPane = useCallback((
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
    const newLeaf = createLeaf(agentType, options.model || agentModels[agentType] || agentModel, options.sessionId);
    newLeaf.pane.role = options.role || roleForAgent(agentType);
    newLeaf.pane.isPrimary = agentType === 'personal';
    const placement = options.placement || 'after';

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
  }, [agentModel, agentModels, paneRoot]);

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
    setSessions((prev) => prev.map((session) => (
      session.id === targetSessionId ? { ...session, model_id: modelId } : session
    )));

    const targetView = sessionViewRefs.current.get(targetSessionId);
    if (targetView?.switchModel) {
      targetView.switchModel(modelId);
    } else if (leafId === focusedLeafId) {
      focusedActions.switchModel(modelId);
    }
  }, [focusedActions, focusedLeafId, layout, paneRoot]);

  // Close a leaf pane
  const handleClosePane = useCallback((leafId: string) => {
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
  }, [agentModel, layout.activeAgent]);

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
      const handler = () => newSession();
      const unsubscribe = window.electronAPI.onNewSession(handler);
      return () => { unsubscribe?.(); };
    }
  }, [newSession]);

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
        />

        {/* Left sidebar */}
        {!layout.sidebarCollapsed && (
          <>
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
              sessions={sessions}
              currentSession={focusedSessionId}
              onNewSession={startFocusedSession}
              onCompactSession={() => focusedActions.compactSession(false)}
              onRewindSession={openFocusedRewind}
              onSwitchSession={switchSession}
              onDeleteSession={deleteSession}
              currentProjectPath={currentProject?.path ?? null}
              currentProject={currentProject}
              fileTree={fileTree}
              expandedPaths={expandedPaths}
              loadingPaths={loadingPaths}
              onTogglePath={handleTogglePath}
              onSelectFile={handleSelectFile}
              onOpenFolder={handleOpenFolder}
              onOpenProjectModal={() => setShowProjectModal(true)}
              onCloseProject={handleCloseProject}
              onRefreshTree={refreshProject}
              isRefreshingProject={isRefreshingProject}
            />
            <ProjectModal
              isOpen={showProjectModal}
              onClose={() => setShowProjectModal(false)}
              onProjectCreated={async (project) => {
                setCurrentProject(project);
                setExpandedPaths(new Set());
                setLoadingPaths(new Set());
                setFileTree(await fetchProjectTreePath());
                setShowProjectModal(false);
                addTerminalLog(`[系统] 已创建项目: ${project.name}`);
              }}
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
              const defaultModel = data.default || modelsList[0]?.id || '';

              // Re-fetch per-agent model settings
              try {
                const settingsRes = await fetch(`${API_BASE}/api/settings`);
                const settingsData = await settingsRes.json();
                setAgentModels({
                  personal: settingsData.personal_agent?.model || defaultModel,
                  coding: settingsData.coding_agent?.model || defaultModel,
                });
              } catch {
                setAgentModels({ personal: defaultModel, coding: defaultModel });
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
          resizeTargetMinimumSize={{ fine: 22, coarse: 34 }}
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
                resizeTargetMinimumSize={{ fine: 22, coarse: 34 }}
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
