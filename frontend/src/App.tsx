import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { Panel, Group, Separator } from 'react-resizable-panels';
import type { PanelImperativeHandle } from 'react-resizable-panels';
import { AnimatePresence, motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { Sidebar } from './components/Sidebar';
import { ChatPanel } from './components/ChatPanel';
import { TerminalPanel } from './components/TerminalPanel';
import { ToolCallView } from './components/ToolCallView';
import { ArtifactPanel } from './components/ArtifactPanel/ArtifactPanel';
import { ChangesPanel } from './components/ChangesPanel';
import { KnowledgePanel } from './components/KnowledgePanel';
import { WorkflowPanel } from './components/WorkflowPanel';
import { McpPanel } from './components/McpPanel';
import { ModelInfo, RoleInfo, ToolCall, ArtifactItem, ProjectInfo, FileNode, OpenFile, EditorGroup, SettingsResponse, FileEdit } from './types';
import { API_BASE } from './config';
import { useChatSession } from './hooks/useChatSession';
import { useLayoutState } from './hooks/useLayoutState';
import { loadRoles } from './lib/db';
import { getLangFromFilename } from './lib/language';
import { Settings, ChevronDown, ChevronUp, ChevronLeft } from 'lucide-react';
import { RoleEditor } from './components/RoleEditor';
import { ProjectModal } from './components/ProjectModal';
import { EditorPanel } from './components/EditorPanel/EditorPanel';
import { SettingsModal } from './components/SettingsModal';
import { ActivityBar } from './components/ActivityBar';
import { WindowControls } from './components/WindowControls';

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

export default function App() {
  const { t } = useTranslation();
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [currentModel, setCurrentModel] = useState<string>('');
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [currentRole, setCurrentRole] = useState<string>(() => localStorage.getItem('agent_default_role') || 'desktop-agent');
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const [sessionId, setSessionId] = useState(() => `session_${Date.now()}`);
  const [sessions, setSessions] = useState<{ id: string; model_id: string; message_count: number }[]>([]);
  const [showRoleEditor, setShowRoleEditor] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  // 项目状态
  const [currentProject, setCurrentProject] = useState<ProjectInfo | null>(null);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [showProjectModal, setShowProjectModal] = useState(false);

  // 布局状态 — centralized hook
  const layout = useLayoutState();

  // 成果状态
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [latestToolCall, setLatestToolCall] = useState<ToolCall | null>(null);

  // 编辑器状态
  const [editorGroups, setEditorGroups] = useState<EditorGroup[]>([
    { id: 'main', activeFileId: null, openFiles: [] },
  ]);
  const [activeEditorGroup, setActiveEditorGroup] = useState('main');

  const didPromptModelSetup = React.useRef(false);
  const rightPanelRef = useRef<PanelImperativeHandle>(null);
  const terminalPanelRef = useRef<PanelImperativeHandle>(null);

  // Sync right panel collapse/expand with layout state
  useEffect(() => {
    const panel = rightPanelRef.current;
    if (!panel) return;
    if (layout.rightPanelVisible && panel.isCollapsed()) {
      panel.expand();
    } else if (!layout.rightPanelVisible && !panel.isCollapsed()) {
      panel.collapse();
    }
  }, [layout.rightPanelVisible]);

  // Sync terminal collapse/expand with layout state
  useEffect(() => {
    const panel = terminalPanelRef.current;
    if (!panel) return;
    if (layout.showTerminal && panel.isCollapsed()) {
      panel.expand();
    } else if (!layout.showTerminal && !panel.isCollapsed()) {
      panel.collapse();
    }
  }, [layout.showTerminal]);

  const {
    messages,
    toolCalls,
    fileEdits,
    terminalLogs,
    isRunning,
    isConnected,
    sendMessage,
    clearSession,
    stopRunning,
    retryLast,
    executeToolDirect,
    resetSession,
    addTerminalLog,
    onToolCallRef,
    onFileEditRef,
    recordFileEdit,
    saveInputDraft,
    loadInputDraft,
    clearInputDraft,
  } = useChatSession(sessionId, currentModel, currentRole);

  // 加载模型列表、角色列表和会话列表
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
          setCurrentModel(defaultModel);
        }
      } catch (err) {
        console.error('[App] Failed to load models:', err);
      }
    };

    const loadRolesData = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/roles`);
        const data = await res.json();
        const builtinRoles: RoleInfo[] = (data.roles || []).map((r: any) => ({
          id: r.id,
          name: r.name,
          description: r.description,
          isBuiltin: true,
        }));
        if (!cancelled) {
          setRoles(builtinRoles);
        }
        // 再尝试加载自定义角色并合并
        try {
          const custom = await loadRoles();
          const customRoles: RoleInfo[] = custom.map((r) => ({
            id: r.id,
            name: r.name,
            description: r.description,
            isBuiltin: false,
          }));
          if (!cancelled) {
            setRoles([...builtinRoles, ...customRoles]);
          }
        } catch (dbErr) {
          console.error('[App] Failed to load custom roles from IndexedDB:', dbErr);
        }
      } catch (err) {
        console.error('[App] Failed to load roles:', err);
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
      await Promise.all([loadModels(), loadRolesData(), loadSettingsReadiness()]);
      if (!cancelled) setIsLoadingModels(false);
    };

    doLoad();
    loadSessions();
    loadCurrentProject();

    // 2秒后检查，如果仍为空则重试一次
    const retryTimer = setTimeout(() => {
      setModels((prevModels) => {
        if (prevModels.length === 0 && !cancelled) {
          doLoad();
        }
        return prevModels;
      });
    }, 2000);

    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
    };
  }, []);

  const loadCurrentProject = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/projects/current`);
      const project = await res.json();
      if (project && project.path) {
        setCurrentProject(project);
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
        setEditorGroups([{ id: 'main', activeFileId: null, openFiles: [] }]);
        setActiveEditorGroup('main');
        loadProjectTree();
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
        setEditorGroups([{ id: 'main', activeFileId: null, openFiles: [] }]);
        setActiveEditorGroup('main');
        addTerminalLog('[系统] 已关闭项目');
      })
      .catch(console.error);
  }, [addTerminalLog]);

  const handleTogglePath = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const handleSelectFile = useCallback(async (path: string, type: 'file' | 'dir') => {
    if (type !== 'file') return;
    if (!currentProject) {
      console.error('[App] No project open');
      return;
    }
    try {
      // 使用绝对路径，避免后端重启后 project_relative 失效
      const filePath = currentProject.path.replace(/\\/g, '/') + '/' + path;
      const res = await fetch(
        `${API_BASE}/api/file/read?path=${encodeURIComponent(filePath)}`
      );
      const data = await res.json();
      if (data.error) {
        console.error('[App] Read file failed:', data.error);
        return;
      }
      const filename = path.split('/').pop() || path;
      const openFile: OpenFile = {
        id: `file:${path}`,
        path,
        name: filename,
        content: data.content || '',
        language: getLangFromFilename(filename),
      };

      setEditorGroups((prev) => {
        const groupIdx = prev.findIndex((g) => g.id === activeEditorGroup);
        if (groupIdx < 0) return prev;
        const group = prev[groupIdx];
        const existingIdx = group.openFiles.findIndex((f) => f.id === openFile.id);

        let newOpenFiles: OpenFile[];
        let newActiveId: string;

        if (existingIdx >= 0) {
          // 已打开，刷新内容并切换
          newOpenFiles = group.openFiles.map((f, i) =>
            i === existingIdx ? { ...f, content: openFile.content } : f
          );
          newActiveId = openFile.id;
        } else {
          // 限制最多 10 个文件，关闭最早未固定的
          let files = group.openFiles;
          if (files.length >= 10) {
            const firstUnpinned = files.findIndex((f) => !f.isPinned);
            if (firstUnpinned >= 0) {
              files = files.filter((_, i) => i !== firstUnpinned);
            }
          }
          newOpenFiles = [...files, openFile];
          newActiveId = openFile.id;
        }

        const newGroups = [...prev];
        newGroups[groupIdx] = { ...group, openFiles: newOpenFiles, activeFileId: newActiveId };
        return newGroups;
      });

      layout.setRightTab('editor');
    } catch (err) {
      console.error('[App] Read file error:', err);
    }
  }, [activeEditorGroup, getLangFromFilename, currentProject]);

  // 编辑器操作
  const handleSelectFileInEditor = useCallback((groupId: string, fileId: string) => {
    setEditorGroups((prev) =>
      prev.map((g) => (g.id === groupId ? { ...g, activeFileId: fileId } : g))
    );
    setActiveEditorGroup(groupId);
  }, []);

  const handleCloseFileInEditor = useCallback((groupId: string, fileId: string) => {
    setEditorGroups((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g;
        const idx = g.openFiles.findIndex((f) => f.id === fileId);
        if (idx < 0) return g;
        const newFiles = g.openFiles.filter((f) => f.id !== fileId);
        let newActive = g.activeFileId;
        if (newActive === fileId) {
          newActive = newFiles[idx]?.id || newFiles[idx - 1]?.id || null;
        }
        return { ...g, openFiles: newFiles, activeFileId: newActive };
      })
    );
  }, []);

  const handleSplitEditor = useCallback(() => {
    setEditorGroups((prev) => {
      if (prev.length >= 2) return prev;
      return [
        ...prev,
        { id: 'secondary', activeFileId: null, openFiles: [] },
      ];
    });
  }, []);

  const handleCloseSplit = useCallback(() => {
    setEditorGroups((prev) => prev.filter((g) => g.id === 'main'));
    setActiveEditorGroup('main');
  }, []);

  const handleMoveToGroup = useCallback((fileId: string, fromGroupId: string, toGroupId: string) => {
    setEditorGroups((prev) => {
      const fromGroup = prev.find((g) => g.id === fromGroupId);
      if (!fromGroup) return prev;
      const file = fromGroup.openFiles.find((f) => f.id === fileId);
      if (!file) return prev;

      return prev.map((g) => {
        if (g.id === fromGroupId) {
          const newFiles = g.openFiles.filter((f) => f.id !== fileId);
          const newActive = g.activeFileId === fileId
            ? (newFiles[0]?.id || null)
            : g.activeFileId;
          return { ...g, openFiles: newFiles, activeFileId: newActive };
        }
        if (g.id === toGroupId) {
          const exists = g.openFiles.find((f) => f.id === fileId);
          if (exists) return { ...g, activeFileId: fileId };
          return { ...g, openFiles: [...g.openFiles, file], activeFileId: fileId };
        }
        return g;
      });
    });
  }, []);

  // 编辑器内容变更（仅更新本地状态，不保存）
  const handleFileContentChange = useCallback((groupId: string, fileId: string, content: string) => {
    setEditorGroups((prev) =>
      prev.map((g) =>
        g.id === groupId
          ? {
            ...g,
            openFiles: g.openFiles.map((f) =>
              f.id === fileId ? { ...f, content, isModified: true } : f
            ),
          }
          : g
      )
    );
  }, []);

  // 保存文件到磁盘
  const handleSaveFile = useCallback(async (groupId: string, fileId: string, content: string) => {
    const file = editorGroups.find(g => g.id === groupId)?.openFiles.find(f => f.id === fileId);
    if (!file) return;

    try {
      const filePath = currentProject?.path.replace(/\\/g, '/') + '/' + file.path;
      const res = await fetch(`${API_BASE}/api/file/write`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath, content }),
      });
      const data = await res.json();
      if (data.error) {
        console.error('[App] Save file failed:', data.error);
        addTerminalLog(`[错误] 保存文件失败: ${data.error}`);
        return;
      }

      // 更新状态：清除修改标记
      setEditorGroups((prev) =>
        prev.map((g) =>
          g.id === groupId
            ? {
              ...g,
              openFiles: g.openFiles.map((f) =>
                f.id === fileId ? { ...f, content, isModified: false, hasConflict: false } : f
              ),
            }
            : g
        )
      );
      addTerminalLog(`[系统] 文件已保存: ${file.name}`);
      if (data.file_edit) {
        recordFileEdit(data.file_edit as FileEdit, false);
      }
    } catch (err) {
      console.error('[App] Save file error:', err);
      addTerminalLog(`[错误] 保存文件出错: ${err}`);
    }
  }, [editorGroups, currentProject, addTerminalLog, recordFileEdit]);

  const loadSessions = useCallback(() => {
    fetch(`${API_BASE}/api/sessions`)
      .then((r) => r.json())
      .then((data) => setSessions(data.sessions || []))
      .catch(console.error);
  }, []);

  // 监听工具调用，检测产物并创建成果
  useEffect(() => {
    onToolCallRef.current = (tc: ToolCall) => {
      setLatestToolCall(tc);

      if (tc.name === 'file_write') {
        const path: string = tc.args?.path || '';

        if (!path.startsWith('preview/')) return;

        const filename = path.replace('preview/', '');
        const ext = filename.split('.').pop()?.toLowerCase();
        const id = `artifact_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`;

        let type: ArtifactItem['type'] = 'code';
        let content = tc.result || '';
        let url: string | undefined;
        let base64: string | undefined;

        if (ext === 'html') {
          type = 'web';
          url = `${API_BASE}/preview/${filename}`;
        } else if (['png', 'jpg', 'jpeg', 'svg', 'gif', 'webp'].includes(ext || '')) {
          type = 'image';
          url = `${API_BASE}/preview/${filename}`;
        } else if (ext === 'csv') {
          type = 'data';
          content = tc.result || '';
        } else if (ext === 'json') {
          type = 'data';
          content = tc.result || '';
        } else if (['mp4', 'webm', 'mov'].includes(ext || '')) {
          type = 'video';
          url = `${API_BASE}/preview/${filename}`;
        } else {
          type = 'code';
          content = tc.result || '';
        }

        const item: ArtifactItem = {
          id,
          type,
          title: filename,
          content,
          url,
          base64,
          timestamp: Date.now(),
          sourceTool: 'file_write',
        };

        setArtifacts((prev) => [...prev, item]);
        layout.setRightTab('artifacts');
      }

      if (tc.name === 'shell_execute') {
        const id = `artifact_term_${Date.now()}`;
        const command = tc.args?.command || '';
        const result = tc.result || '';
        const existingIdx = artifacts.findIndex((a) => a.type === 'terminal' && a.sourceTool === 'shell_execute');

        if (existingIdx >= 0) {
          // 追加到现有终端成果
          setArtifacts((prev) => {
            const next = [...prev];
            next[existingIdx] = {
              ...next[existingIdx],
              content: next[existingIdx].content + `\n$ ${command}\n${result}`,
              timestamp: Date.now(),
            };
            return next;
          });
        } else {
          const item: ArtifactItem = {
            id,
            type: 'terminal',
            title: '终端输出',
            content: `$ ${command}\n${result}`,
            timestamp: Date.now(),
            sourceTool: 'shell_execute',
          };
          setArtifacts((prev) => [...prev, item]);
        }
        layout.setRightTab('artifacts');
      }

      // browser_screenshot 的截图通过独立的 image 事件传递，此处不处理
    };
  }, [onToolCallRef, artifacts]);

  useEffect(() => {
    onFileEditRef.current = (edit: FileEdit) => {
      const editPath = normalizePath(edit.path);
      const projectRoot = currentProject ? normalizePath(currentProject.path) : '';
      const relativePath = projectRoot && editPath.startsWith(projectRoot + '/')
        ? edit.path.replace(/\\/g, '/').slice(currentProject!.path.replace(/\\/g, '/').length + 1)
        : edit.path.replace(/\\/g, '/');

      setEditorGroups((prev) =>
        prev.map((g) => ({
          ...g,
          openFiles: g.openFiles.map((f) => {
            const filePath = normalizePath(f.path);
            const matches = filePath === normalizePath(relativePath) || editPath.endsWith('/' + filePath);
            if (!matches) return f;

            const hasLocalConflict = !!f.isModified && edit.old_text != null && f.content !== edit.old_text;
            if (hasLocalConflict) {
              return { ...f, hasConflict: true, isModified: true };
            }
            return {
              ...f,
              content: edit.new_text ?? f.content,
              isModified: false,
              hasConflict: false,
            };
          }),
        }))
      );

      layout.setRightTab('changes');
      layout.setRightPanelVisible(true);
      if (edit.truncated) {
        addTerminalLog(`[Edit] ${edit.path} changed; full text was too large for inline diff`);
      }
    };
    return () => {
      onFileEditRef.current = null;
    };
  }, [onFileEditRef, currentProject, layout, addTerminalLog]);

  // Electron 菜单事件
  useEffect(() => {
    if (window.electronAPI?.onNewSession) {
      const handler = () => newSession();
      const unsubscribe = window.electronAPI.onNewSession(handler);
      return () => {
        unsubscribe?.();
      };
    }
  }, []);

  const switchSession = useCallback(
    (newSessionId: string) => {
      resetSession();
      setSessionId(newSessionId);
    },
    [resetSession]
  );

  const newSession = useCallback(() => {
    switchSession(`session_${Date.now()}`);
  }, [switchSession]);

  const handleRoleChange = useCallback((roleId: string) => {
    setCurrentRole(roleId);
    localStorage.setItem('agent_default_role', roleId);
    // 切换角色时自动新建会话
    resetSession();
    setSessionId(`session_${Date.now()}`);
    addTerminalLog(`[系统] 已切换到角色: ${roles.find(r => r.id === roleId)?.name || roleId}，新建会话`);
  }, [resetSession, roles, addTerminalLog]);

  const handleRolesChanged = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/roles`);
      const data = await r.json();
      const builtinRoles: RoleInfo[] = (data.roles || []).map((r: any) => ({
        id: r.id,
        name: r.name,
        description: r.description,
        isBuiltin: true,
      }));
      setRoles(builtinRoles);
      try {
        const custom = await loadRoles();
        const customRoles: RoleInfo[] = custom.map((r) => ({
          id: r.id,
          name: r.name,
          description: r.description,
          isBuiltin: false,
        }));
        setRoles([...builtinRoles, ...customRoles]);
      } catch (dbErr) {
        console.error('[App] Failed to load custom roles:', dbErr);
      }
    } catch (err) {
      console.error('[App] Failed to reload roles:', err);
    }
  }, []);

  const deleteSession = useCallback(
    async (id: string) => {
      await fetch(`${API_BASE}/api/sessions/${id}`, { method: 'DELETE' });
      loadSessions();
      if (id === sessionId) {
        newSession();
      }
    },
    [sessionId, newSession, loadSessions]
  );

  // 全局快捷键
  useHotkeys('ctrl+k, cmd+k', (e) => {
    e.preventDefault();
    // 聚焦到搜索框的逻辑由 ChatPanel 内部处理
    // 这里通过 ref 或直接操作 DOM 触发
    const searchInput = document.querySelector('[data-search-input]') as HTMLInputElement;
    searchInput?.focus();
  }, { enableOnFormTags: true });

  useHotkeys('ctrl+l, cmd+l', (e) => {
    e.preventDefault();
    clearSession();
  });

  useHotkeys('ctrl+b, cmd+b', (e) => {
    e.preventDefault();
    layout.setSidebarCollapsed((v) => !v);
  });

  useHotkeys('ctrl+backslash, cmd+backslash', (e) => {
    e.preventDefault();
    layout.setRightPanelVisible((v) => !v);
  });

  useHotkeys('ctrl+j, cmd+j', (e) => {
    e.preventDefault();
    layout.setShowTerminal((v) => !v);
  });

  useHotkeys('esc', () => {
    if (isRunning) {
      stopRunning();
    }
  });

  // 连接状态变化时记录日志
  useEffect(() => {
    if (isConnected) {
      addTerminalLog('[系统] WebSocket 已连接');
    } else {
      addTerminalLog('[系统] WebSocket 已断开，尝试重连...');
    }
  }, [isConnected, addTerminalLog]);

  return (
    <div className="h-screen flex flex-col bg-app text-fg overflow-hidden">
      {/* 顶部标题栏 */}
      <div className="h-10 bg-surface border-b border-border flex items-center px-4 justify-between select-none app-drag">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm font-medium">Desktop Agent</span>
          <span className="text-xs text-fg-muted ml-2">{isRunning ? '● Running' : '○ Ready'}</span>
        </div>
        <div className="flex items-center gap-2">
          <WindowControls
            showTerminal={layout.showTerminal}
            rightPanelVisible={layout.rightPanelVisible}
            onToggleTerminal={layout.toggleTerminal}
            onToggleRightPanel={layout.toggleRightPanel}
            onResetLayout={layout.resetLayout}
          />
          <span className="text-xs text-fg-secondary bg-surface-hover/80 px-2 py-1 rounded border border-border">
            {models.find(m => m.id === currentModel)?.name || currentModel}
          </span>
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

      {/* 主内容区 */}
      <div className="flex-1 flex overflow-hidden">
        {/* Activity Bar — always visible */}
        <ActivityBar
          activeSection={layout.activeSection}
          sidebarCollapsed={layout.sidebarCollapsed}
          onSectionChange={layout.setActiveSection}
          onToggleSidebar={layout.toggleSidebar}
        />

        {/* 左侧边栏 */}
        {!layout.sidebarCollapsed && (
          <>
            <Sidebar
              activeSection={layout.activeSection}
              onSectionChange={layout.setActiveSection}
              roles={roles}
              currentRole={currentRole}
              onRoleChange={handleRoleChange}
              onOpenRoleEditor={() => setShowRoleEditor(true)}
              onOpenSettings={() => setShowSettings(true)}
              onClear={clearSession}
              onExecuteTool={executeToolDirect}
              isConnected={isConnected}
              sessions={sessions}
              currentSession={sessionId}
              onNewSession={newSession}
              onSwitchSession={switchSession}
              onDeleteSession={deleteSession}
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
                setEditorGroups([{ id: 'main', activeFileId: null, openFiles: [] }]);
                setActiveEditorGroup('main');
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
          currentModel={currentModel}
          onSettingsChanged={async () => {
            try {
              const res = await fetch(`${API_BASE}/api/models`);
              const data = await res.json();
              const modelsList = data.models || [];
              setModels(modelsList);
              const defaultModel = data.default || modelsList[0]?.id || '';
              setCurrentModel(defaultModel);
            } catch (err) {
              console.error('[App] Failed to refresh models after settings change:', err);
            }
          }}
        />

        <RoleEditor
          isOpen={showRoleEditor}
          onClose={() => setShowRoleEditor(false)}
          onRolesChanged={handleRolesChanged}
        />

        {/* 中间 + 右侧面板 — horizontal Group */}
        <Group orientation="horizontal" className="flex-1 min-w-0" resizeTargetMinimumSize={{ fine: 16, coarse: 24 }}>
          {/* 中间 + 底部面板 */}
          <Panel>
            <div className="flex flex-col h-full">
              <Group orientation="vertical" className="flex-1 min-h-0" resizeTargetMinimumSize={{ fine: 16, coarse: 24 }}>
                <Panel>
                  <ChatPanel
                    messages={messages}
                    toolCalls={toolCalls}
                    onSend={sendMessage}
                    onStop={stopRunning}
                    onRetry={retryLast}
                    isRunning={isRunning}
                    onDraftSave={saveInputDraft}
                    onDraftLoad={loadInputDraft}
                    onDraftClear={clearInputDraft}
                  />
                </Panel>

                <Separator className="h-4 bg-border hover:bg-accent/30 active:bg-accent/40 transition-colors cursor-row-resize flex items-center justify-center">
                  <div className="w-8 h-0.5 rounded-full bg-fg-muted/30" />
                </Separator>

                <Panel
                  id="terminal"
                  panelRef={terminalPanelRef}
                  collapsible
                  collapsedSize={0}
                  defaultSize={100}
                  minSize={0}
                  maxSize={800}
                  onResize={(size) => {
                    if (size.asPercentage <= 1) {
                      layout.setShowTerminal(false);
                    } else if (!layout.showTerminal) {
                      layout.setShowTerminal(true);
                    }
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

          {/* Right panel — always in Group, uses collapsible */}
          <Separator className="w-4 bg-border hover:bg-accent/30 active:bg-accent/40 transition-colors cursor-col-resize flex items-center justify-center">
            <div className="h-8 w-0.5 rounded-full bg-fg-muted/30" />
          </Separator>
          <Panel
            panelRef={rightPanelRef}
            defaultSize={800} minSize={0} maxSize={1600}
            collapsible collapsedSize={0}
            onResize={(size) => {
              if (size.asPercentage <= 1) {
                layout.setRightPanelVisible(false);
              } else if (!layout.rightPanelVisible) {
                layout.setRightPanelVisible(true);
              }
            }}
          >
            <div className="bg-surface/50 flex flex-col h-full min-w-0">
              <div className="flex border-b border-border overflow-x-auto max-w-full min-w-0">
                <button
                  onClick={() => layout.setRightTab('tools')}
                  className={`shrink-0 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${layout.rightTab === 'tools' ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:text-fg'
                    }`}
                >
                  Tool Calls
                </button>
                <button
                  onClick={() => layout.setRightTab('changes')}
                  className={`shrink-0 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${layout.rightTab === 'changes' ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:text-fg'
                    }`}
                >
                  Changes
                </button>
                <button
                  onClick={() => layout.setRightTab('artifacts')}
                  className={`shrink-0 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${layout.rightTab === 'artifacts' ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:text-fg'
                    }`}
                >
                  Artifacts
                </button>
                <button
                  onClick={() => layout.setRightTab('editor')}
                  className={`shrink-0 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${layout.rightTab === 'editor' ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:text-fg'
                    }`}
                >
                  Editor
                </button>
                <button
                  onClick={() => layout.setRightTab('knowledge')}
                  className={`shrink-0 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${layout.rightTab === 'knowledge' ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:text-fg'
                    }`}
                >
                  Knowledge
                </button>
                <button
                  onClick={() => layout.setRightTab('workflow')}
                  className={`shrink-0 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${layout.rightTab === 'workflow' ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:text-fg'
                    }`}
                >
                  Workflows
                </button>
                <button
                  onClick={() => layout.setRightTab('mcp')}
                  className={`shrink-0 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${layout.rightTab === 'mcp' ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:text-fg'
                    }`}
                >
                  MCP
                </button>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden">
                {layout.rightTab === 'tools' && (
                  <div className="h-full overflow-y-auto p-2">
                    {toolCalls.length === 0 && (
                      <div className="text-xs text-fg-muted text-center mt-4">No tool calls yet</div>
                    )}
                    {toolCalls.map((tc, i) => (
                      <ToolCallView
                        key={tc.timestamp + i}
                        name={tc.name}
                        args={tc.args}
                        result={tc.result}
                        status={tc.result.startsWith('[ERROR]') ? 'error' : 'success'}
                        durationMs={tc.durationMs}
                        workerEvents={tc.workerEvents}
                      />
                    ))}
                  </div>
                )}
                {layout.rightTab === 'artifacts' && (
                  <ArtifactPanel artifacts={artifacts} isRunning={isRunning} latestToolCall={latestToolCall} />
                )}
                {layout.rightTab === 'editor' && (
                  <EditorPanel
                    groups={editorGroups}
                    activeGroupId={activeEditorGroup}
                    projectName={currentProject?.name || '未打开项目'}
                    onSelectFile={handleSelectFileInEditor}
                    onCloseFile={handleCloseFileInEditor}
                    onMoveToGroup={handleMoveToGroup}
                    onSplitEditor={handleSplitEditor}
                    onCloseSplit={handleCloseSplit}
                    onSetActiveGroup={setActiveEditorGroup}
                    onFileContentChange={handleFileContentChange}
                    onSaveFile={handleSaveFile}
                  />
                )}
                {layout.rightTab === 'changes' && (
                  <ChangesPanel edits={fileEdits} onOpenFile={(path) => {
                    if (!currentProject) return;
                    const projectRoot = currentProject.path.replace(/\\/g, '/');
                    const normalized = path.replace(/\\/g, '/');
                    const relative = normalizePath(normalized).startsWith(normalizePath(projectRoot) + '/')
                      ? normalized.slice(projectRoot.length + 1)
                      : normalized;
                    handleSelectFile(relative, 'file');
                  }} />
                )}
                {layout.rightTab === 'knowledge' && <KnowledgePanel />}
                {layout.rightTab === 'workflow' && <WorkflowPanel />}
                {layout.rightTab === 'mcp' && <McpPanel />}
              </div>
            </div>
          </Panel>
        </Group>

        {/* Right panel expand strip — shown when panel is collapsed */}
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
              onClick={() => { layout.setRightTab('tools'); layout.setRightPanelVisible(true); }}
              className={`w-6 h-6 rounded flex items-center justify-center text-xs ${layout.rightTab === 'tools' ? 'text-fg bg-surface-alt' : 'text-fg-muted hover:text-fg hover:bg-surface-hover'} transition-colors`}
              title="Tool Calls"
            >T</button>
            <button
              type="button"
              onClick={() => { layout.setRightTab('editor'); layout.setRightPanelVisible(true); }}
              className={`w-6 h-6 rounded flex items-center justify-center text-xs ${layout.rightTab === 'editor' ? 'text-fg bg-surface-alt' : 'text-fg-muted hover:text-fg hover:bg-surface-hover'} transition-colors`}
              title="Editor"
            >E</button>
            <button
              type="button"
              onClick={() => { layout.setRightTab('knowledge'); layout.setRightPanelVisible(true); }}
              className={`w-6 h-6 rounded flex items-center justify-center text-xs ${layout.rightTab === 'knowledge' ? 'text-fg bg-surface-alt' : 'text-fg-muted hover:text-fg hover:bg-surface-hover'} transition-colors`}
              title="Knowledge"
            >K</button>
          </div>
        )}
      </div>
    </div>
  );
}
