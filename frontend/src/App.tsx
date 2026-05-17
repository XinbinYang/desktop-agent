import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { Panel, Group, Separator } from 'react-resizable-panels';
import type { GroupImperativeHandle, PanelImperativeHandle } from 'react-resizable-panels';
import { AnimatePresence, motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { Sidebar } from './components/Sidebar';
import { SessionView, type SessionViewHandle } from './components/session/SessionView';
import { PaneRenderer } from './components/session/PaneRenderer';
import type { PaneNode, SessionPane, SplitNode } from './components/session/PaneTypes';
import {
  nextNodeId,
  collectLeaves,
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

function createSessionPane(agentType: AgentType, model: string, sessionId = `session_${Date.now()}`): SessionPane {
  return {
    id: `pane_${Date.now()}`,
    sessionId,
    model,
    agentType,
    role: roleForAgent(agentType),
  };
}

function createLeaf(agentType: AgentType, model: string, sessionId?: string): PaneNode {
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

const NOOP_ACTIONS: SessionActions = {
  sendMessage: () => {},
  stopRunning: () => {},
  retryLast: () => {},
  executeToolDirect: () => {},
  addTerminalLog: (_msg: string) => {},
  approvePlan: () => {},
  buildPlan: () => {},
  rejectPlan: () => {},
  updatePlanDecision: () => {},
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
  const [showProjectModal, setShowProjectModal] = useState(false);

  const layout = useLayoutState();
  const agentModel = agentModels[layout.activeAgent] || '';

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
  const didPromptModelSetup = React.useRef(false);
  const mainGroupRef = useRef<GroupImperativeHandle>(null);
  const centerGroupRef = useRef<GroupImperativeHandle>(null);
  const rightPanelRef = useRef<PanelImperativeHandle>(null);
  const terminalPanelRef = useRef<PanelImperativeHandle>(null);

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

  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const addTerminalLog = useCallback((msg: string) => {
    setTerminalLogs((prev) => [...prev, msg]);
  }, []);

  // Slash command handler — delegates to focused session actions
  const handleSlashCommand = useCallback((command: string, _args: string) => {
    const a = focusedActions;
    switch (command) {
      case 'clear':
        addTerminalLog('[命令] 已清除会话');
        break;
      case 'help':
        addTerminalLog('[帮助] 可用命令: /help /clear /compact /model /role /project /config /screenshot /skills');
        break;
      case 'compact':
        if (a) a.sendMessage('__compact__', undefined, { chatMode: 'agent' });
        addTerminalLog('[命令] 正在压缩对话上下文...');
        break;
      case 'config':
        setShowSettings(true);
        break;
      case 'screenshot':
        if (a) a.executeToolDirect('screenshot', {});
        addTerminalLog('[命令] 正在截图...');
        break;
      default:
        addTerminalLog(`[命令] 未知命令: /${command}`);
    }
  }, [focusedActions, addTerminalLog]);

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

  const loadCurrentProject = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/projects/current`);
      const data = await res.json();
      if (data.path && !data.error) {
        setCurrentProject(data);
        loadProjectTree();
      }
    } catch (err) {
      console.error('[App] Failed to load current project:', err);
    }
  }, []);

  const loadProjectTree = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/projects/tree`);
      const data = await res.json();
      setFileTree(data.nodes || []);
    } catch (err) {
      console.error('[App] Failed to load project tree:', err);
    }
  }, []);

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
        loadProjectTree();
        loadSessions(project.path);
        addTerminalLog(`[系统] 已打开项目: ${project.name}`);
      } catch (err) {
        console.error('[App] Open project error:', err);
      }
    }
  }, [loadProjectTree, addTerminalLog]);

  const handleCloseProject = useCallback(() => {
    fetch(`${API_BASE}/api/projects/close`, { method: 'POST' })
      .then(() => {
        setCurrentProject(null);
        setFileTree([]);
        setExpandedPaths(new Set());
        loadSessions();
      })
      .catch(console.error);
  }, []);

  const handleTogglePath = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  // handleSelectFile → opens file in focused session's editor
  const handleSelectFile = useCallback(async (path: string, type: 'file' | 'dir') => {
    if (type !== 'file' || !currentProject) return;
    try {
      const filePath = currentProject.path.replace(/\\/g, '/') + '/' + path;
      const res = await fetch(`${API_BASE}/api/file/read?path=${encodeURIComponent(filePath)}`);
      if (!res.ok) return;
      const data = await res.json();
      const content = data.content ?? '';
      const name = path.split('/').pop() || path;
      const language = getLangFromFilename(name);
      const h = sessionViewRefs.current.get(focusedSessionId);
      if (h) {
        h.openFile(path, content, language);
        layout.setRightZone('workspace');
        setWorkspaceView('editor');
      }
    } catch (err) {
      console.error('[App] Read file error:', err);
    }
  }, [currentProject, focusedSessionId, layout]);

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
      loadProjectTree();
      addTerminalLog(`[Run] opened worktree: ${worktreePath}`);
    } catch (err) {
      addTerminalLog(`[Run] open worktree error: ${err}`);
    }
  }, [addTerminalLog, loadProjectTree]);

  const loadSessions = useCallback((projectPath?: string | null) => {
    const url = projectPath
      ? `${API_BASE}/api/sessions?project_path=${encodeURIComponent(projectPath)}`
      : `${API_BASE}/api/sessions`;
    fetch(url)
      .then((r) => r.json())
      .then((data) => setSessions(data.sessions || []))
      .catch(console.error);
  }, []);

  // ---- Session pane management (tree-based) ----

  const switchSession = useCallback((newSessionId: string) => {
    const target = sessions.find((s) => s.id === newSessionId);
    const targetAgent = target ? normalizeAgentType(target.agent_type, target.role_id) : layout.activeAgent;
    layout.setActiveAgent(targetAgent);
    setPaneRoot((prev) => {
      const leaf = findLeafById(prev, focusedLeafId);
      if (!leaf) return prev;
      const newPane: SessionPane = {
        ...leaf.pane,
        sessionId: newSessionId,
        model: target?.model_id || agentModels[targetAgent] || agentModel,
        agentType: targetAgent,
        role: target?.role_id || roleForAgent(targetAgent),
      };
      return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
    });
  }, [focusedLeafId, sessions, agentModel, agentModels, layout]);

  const newSession = useCallback(() => {
    const id = `session_${Date.now()}`;
    setPaneRoot((prev) => {
      const leaf = findLeafById(prev, focusedLeafId);
      if (!leaf) return prev;
      const newPane: SessionPane = {
        ...leaf.pane,
        sessionId: id,
        model: agentModel,
        agentType: layout.activeAgent,
        role: roleForAgent(layout.activeAgent),
      };
      return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
    });
  }, [focusedLeafId, agentModel, layout.activeAgent]);

  const deleteSession = useCallback(async (id: string) => {
    await fetch(`${API_BASE}/api/sessions/${id}`, { method: 'DELETE' });
    loadSessions();
    // If the deleted session is the focused one, create a new one in that leaf
    if (focusedSessionId === id) {
      const newId = `session_${Date.now()}`;
      setPaneRoot((prev) => {
        const leaf = findLeafById(prev, focusedLeafId);
        if (!leaf) return prev;
        const newPane: SessionPane = {
          ...leaf.pane,
          sessionId: newId,
          model: agentModel,
          agentType: layout.activeAgent,
          role: roleForAgent(layout.activeAgent),
        };
        return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
      });
    }
  }, [focusedSessionId, focusedLeafId, agentModel, layout.activeAgent, loadSessions]);

  // Split a leaf into two panes (drag to edge)
  const handleSplitPane = useCallback((
    leafId: string,
    direction: 'horizontal' | 'vertical',
    options: SplitPaneOptions = {},
  ) => {
    const agentType = options.agentType || (options.role ? agentForRole(options.role) : layout.activeAgent);
    const newLeaf = createLeaf(agentType, options.model || agentModel, options.sessionId);
    newLeaf.pane.role = options.role || roleForAgent(agentType);
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
  }, [agentModel, layout.activeAgent]);

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
      <div className="h-10 bg-surface border-b border-border flex items-center px-4 justify-between select-none app-drag">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-success' : 'bg-danger'}`} />
          <span className="text-sm font-semibold text-fg-secondary">Desktop Agent</span>
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
            value={agentModel}
            title={`${layout.activeAgent === 'personal' ? 'Personal Agent' : 'Coding Agent'} 模型`}
            aria-label="切换模型"
            onChange={(e) => {
              const newModel = e.target.value;
              setAgentModels(prev => ({ ...prev, [layout.activeAgent]: newModel }));
              setPaneRoot((prev) => {
                const leaf = findLeafById(prev, focusedLeafId);
                if (!leaf) return prev;
                const newPane = { ...leaf.pane, model: newModel };
                return replaceNode(prev, focusedLeafId, { ...leaf, pane: newPane });
              });
              saveAgentModelPreference(layout.activeAgent, newModel);
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
          onAgentChange={handleAgentChange}
          onToggleSidebar={layout.toggleSidebar}
        />

        {/* Left sidebar */}
        {!layout.sidebarCollapsed && (
          <>
            <Sidebar
              activeSection={layout.activeSection}
              activeAgent={layout.activeAgent}
              onSectionChange={layout.setActiveSection}
              agentModel={agentModel}
              onAgentChange={handleAgentChange}
              onOpenPersonalWorkspace={() => {
                layout.setRightPanelVisible(true);
                layout.setRightZone('workspace');
              }}
              onOpenSettings={() => setShowSettings(true)}
              onClear={() => { if (focusedActions) focusedActions.sendMessage('__compact__', undefined, { chatMode: 'agent' }); }}
              onExecuteTool={focusedActions.executeToolDirect}
              isConnected={isConnected}
              sessions={sessions}
              currentSession={focusedSessionId}
              onNewSession={newSession}
              onSwitchSession={switchSession}
              onDeleteSession={deleteSession}
              currentProjectPath={currentProject?.path ?? null}
              currentProject={currentProject}
              fileTree={fileTree}
              expandedPaths={expandedPaths}
              onTogglePath={handleTogglePath}
              onSelectFile={handleSelectFile}
              onOpenFolder={handleOpenFolder}
              onOpenProjectModal={() => setShowProjectModal(true)}
              onCloseProject={handleCloseProject}
              onRefreshTree={loadProjectTree}
            />
            <ProjectModal
              isOpen={showProjectModal}
              onClose={() => setShowProjectModal(false)}
              onProjectCreated={(project) => {
                setCurrentProject(project);
                loadProjectTree();
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
          currentModel={agentModel}
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
              handleAgentChange(switchSuggestion.to);
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
                    onFocus={setFocusedLeafId}
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
                    currentModel={agentModel}
                    currentAgentType={layout.activeAgent}
                    currentRole={roleForAgent(layout.activeAgent)}
                    onSnapshot={handleSessionSnapshot}
                    onCommand={handleSlashCommand}
                    runAction={runAction}
                    openRunWorktree={openRunWorktree}
                    handleOpenFileFromPanel={handleOpenFileFromPanel}
                    handleOpenFileFromPanelWithLine={handleOpenFileFromPanelWithLine}
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
                {layout.rightZone === 'workspace' && layout.activeAgent === 'personal' && (
                  <PersonalWorkspacePanel />
                )}
                {layout.rightZone === 'workspace' && layout.activeAgent !== 'personal' && (
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
