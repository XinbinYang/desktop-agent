import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { Sidebar } from './components/Sidebar';
import { ChatPanel } from './components/ChatPanel';
import { TerminalPanel } from './components/TerminalPanel';
import { ToolCallView } from './components/ToolCallView';
import { ArtifactPanel } from './components/ArtifactPanel/ArtifactPanel';
import { KnowledgePanel } from './components/KnowledgePanel';
import { WorkflowPanel } from './components/WorkflowPanel';
import { McpPanel } from './components/McpPanel';
import { ModelInfo, RoleInfo, ToolCall, ArtifactItem, ProjectInfo, FileNode, OpenFile, EditorGroup } from './types';
import { API_BASE } from './config';
import { useChatSession } from './hooks/useChatSession';
import { loadRoles } from './lib/db';
import { getLangFromFilename } from './lib/language';
import { Settings } from 'lucide-react';
import { RoleEditor } from './components/RoleEditor';
import { ProjectModal } from './components/ProjectModal';
import { EditorPanel } from './components/EditorPanel/EditorPanel';
import { SettingsModal } from './components/SettingsModal';

export default function App() {
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

  // 布局状态
  const [showTerminal, setShowTerminal] = useState(true);
  const [rightTab, setRightTab] = useState<'tools' | 'artifacts' | 'editor' | 'knowledge' | 'workflow' | 'mcp'>('tools');
  const [rightWidth, setRightWidth] = useState(320);
  const [terminalHeight, setTerminalHeight] = useState(192);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // 成果状态
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [latestToolCall, setLatestToolCall] = useState<ToolCall | null>(null);

  // 编辑器状态
  const [editorGroups, setEditorGroups] = useState<EditorGroup[]>([
    { id: 'main', activeFileId: null, openFiles: [] },
  ]);
  const [activeEditorGroup, setActiveEditorGroup] = useState('main');

  const isResizingRight = useRef(false);
  const isResizingBottom = useRef(false);

  const {
    messages,
    toolCalls,
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
        console.log('[App] Fetching models from', `${API_BASE}/api/models`);
        const res = await fetch(`${API_BASE}/api/models`);
        console.log('[App] Models response status:', res.status);
        const data = await res.json();
        console.log('[App] Models data:', data);
        if (!cancelled) {
          const modelsList = data.models || [];
          setModels(modelsList);
          const defaultModel = data.default || modelsList[0]?.id || '';
          setCurrentModel(defaultModel);
          console.log('[App] Set current model to:', defaultModel);
        }
      } catch (err) {
        console.error('[App] Failed to load models:', err);
      }
    };

    const loadRolesData = async () => {
      try {
        console.log('[App] Fetching roles from', `${API_BASE}/api/roles`);
        const res = await fetch(`${API_BASE}/api/roles`);
        console.log('[App] Roles response status:', res.status);
        const data = await res.json();
        console.log('[App] Roles data:', data);
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

    const doLoad = async () => {
      await Promise.all([loadModels(), loadRolesData()]);
      if (!cancelled) setIsLoadingModels(false);
    };

    doLoad();
    loadSessions();
    loadCurrentProject();

    // 2秒后检查，如果仍为空则重试一次
    const retryTimer = setTimeout(() => {
      setModels((prevModels) => {
        if (prevModels.length === 0 && !cancelled) {
          console.log('[App] Models still empty after 2s, retrying...');
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

      setRightTab('editor');
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
                  f.id === fileId ? { ...f, isModified: false } : f
                ),
              }
            : g
        )
      );
      addTerminalLog(`[系统] 文件已保存: ${file.name}`);
    } catch (err) {
      console.error('[App] Save file error:', err);
      addTerminalLog(`[错误] 保存文件出错: ${err}`);
    }
  }, [editorGroups, currentProject, addTerminalLog]);

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
        
        // 检测是否修改了已打开的文件，标记为 isModified
        setEditorGroups((prev) =>
          prev.map((g) => ({
            ...g,
            openFiles: g.openFiles.map((f) =>
              f.path === path || f.path.endsWith('/' + path) || path.endsWith('/' + f.path)
                ? { ...f, isModified: true }
                : f
            ),
          }))
        );
        
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
        setRightTab('artifacts');
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
        setRightTab('artifacts');
      }

      // browser_screenshot 的截图通过独立的 image 事件传递，此处不处理
    };
  }, [onToolCallRef, artifacts]);

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
    setSidebarCollapsed((v) => !v);
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

  // 拖拽调整右侧面板宽度
  const startResizeRight = useCallback((e: React.MouseEvent) => {
    isResizingRight.current = true;
    const startX = e.clientX;
    const startWidth = rightWidth;
    const handleMove = (moveEvent: MouseEvent) => {
      if (!isResizingRight.current) return;
      const delta = startX - moveEvent.clientX;
      setRightWidth(Math.max(200, Math.min(1400, startWidth + delta)));
    };
    const handleUp = () => {
      isResizingRight.current = false;
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
    };
    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
  }, [rightWidth]);

  // 拖拽调整底部终端高度
  const startResizeBottom = useCallback((e: React.MouseEvent) => {
    isResizingBottom.current = true;
    const startY = e.clientY;
    const startHeight = terminalHeight;
    const handleMove = (moveEvent: MouseEvent) => {
      if (!isResizingBottom.current) return;
      const delta = moveEvent.clientY - startY;
      setTerminalHeight(Math.max(80, Math.min(600, startHeight + delta)));
    };
    const handleUp = () => {
      isResizingBottom.current = false;
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
    };
    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
  }, [terminalHeight]);

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-gray-100 overflow-hidden">
      {/* 顶部标题栏 */}
      <div className="h-10 bg-gray-800 border-b border-gray-700 flex items-center px-4 justify-between select-none app-drag">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm font-medium">Desktop Agent</span>
          <span className="text-xs text-gray-500 ml-2">{isRunning ? '● 运行中' : '○ 就绪'}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400 bg-gray-700/50 px-2 py-1 rounded border border-gray-600">
            {models.find(m => m.id === currentModel)?.name || currentModel}
          </span>
          <button
            type="button"
            onClick={() => setShowSettings(true)}
            className="text-gray-400 hover:text-white p-1 rounded hover:bg-gray-700 transition-colors"
            title="设置"
          >
            <Settings className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* 主内容区 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧边栏 */}
        {!sidebarCollapsed && (
          <>
            <Sidebar
              roles={roles}
              currentRole={currentRole}
              onRoleChange={handleRoleChange}
              onOpenRoleEditor={() => setShowRoleEditor(true)}
              onOpenSettings={() => setShowSettings(true)}
              onClear={clearSession}
              onToggleTerminal={() => setShowTerminal((v) => !v)}
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

        {/* 中间 + 底部面板 */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 min-h-0">
            <ChatPanel
              messages={messages}
              onSend={sendMessage}
              onStop={stopRunning}
              onRetry={retryLast}
              isRunning={isRunning}
              onDraftSave={saveInputDraft}
              onDraftLoad={loadInputDraft}
              onDraftClear={clearInputDraft}
            />
          </div>

          {/* 底部终端拖拽条 */}
          {showTerminal && (
            <div
              className="h-1 bg-gray-700 cursor-row-resize hover:bg-agent-500/30 shrink-0"
              onMouseDown={startResizeBottom}
              title="拖拽调整终端高度"
            />
          )}

          {showTerminal && (
            <div style={{ height: terminalHeight, minHeight: 80, maxHeight: 600 }}>
              <TerminalPanel logs={terminalLogs} />
            </div>
          )}
        </div>

        {/* 右侧 Tab 面板（工具调用 / 预览） */}
        <div
          className="border-l border-gray-700 bg-gray-800/50 flex flex-col relative"
          style={{ width: rightWidth, minWidth: 200, maxWidth: 1400 }}
        >
          {/* 拖拽分隔条 */}
          <div
            className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-agent-500/30 z-10"
            onMouseDown={startResizeRight}
          />
          <div className="flex border-b border-gray-700">
            <button
              onClick={() => setRightTab('tools')}
              className={`flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${
                rightTab === 'tools' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              工具调用
            </button>
            <button
              onClick={() => setRightTab('artifacts')}
              className={`flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${
                rightTab === 'artifacts' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              成果
            </button>
            <button
              onClick={() => setRightTab('editor')}
              className={`flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${
                rightTab === 'editor' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              编辑器
            </button>
            <button
              onClick={() => setRightTab('knowledge')}
              className={`flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${
                rightTab === 'knowledge' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              知识库
            </button>
            <button
              onClick={() => setRightTab('workflow')}
              className={`flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${
                rightTab === 'workflow' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              工作流
            </button>
            <button
              onClick={() => setRightTab('mcp')}
              className={`flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wider ${
                rightTab === 'mcp' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              MCP
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-hidden">
            {rightTab === 'tools' && (
              <div className="h-full overflow-y-auto p-2">
                {toolCalls.length === 0 && (
                  <div className="text-xs text-gray-500 text-center mt-4">暂无工具调用</div>
                )}
                {toolCalls.map((tc, i) => (
                  <ToolCallView key={tc.timestamp + i} toolCall={tc} />
                ))}
              </div>
            )}
            {rightTab === 'artifacts' && (
              <ArtifactPanel artifacts={artifacts} isRunning={isRunning} latestToolCall={latestToolCall} />
            )}
            {rightTab === 'editor' && (
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
            {rightTab === 'knowledge' && <KnowledgePanel />}
            {rightTab === 'workflow' && <WorkflowPanel />}
            {rightTab === 'mcp' && <McpPanel />}
          </div>
        </div>
      </div>
    </div>
  );
}
