import React, { useState, useCallback, useEffect, useRef, useImperativeHandle, forwardRef, useMemo } from 'react';
import { ChatPanel } from '../ChatPanel';
import { useChatSession } from '../../hooks/useChatSession';
import type { WorkspaceView } from '../workspace/WorkspacePanel';
import type { SessionSnapshot, SessionActions } from '../../contexts/FocusedSessionContext';
import type {
  ToolCall,
  ArtifactItem,
  ProjectInfo,
  EditorGroup,
  OpenFile,
  FileEdit,
  ClientChatMode,
  ThinkingIntensity,
  AgentType,
} from '../../types';
import { API_BASE } from '../../config';
import { getLangFromFilename } from '../../lib/language';

// ---- Types ----

interface SessionViewProps {
  sessionId: string;
  model: string;
  agentType: AgentType;
  role: string;
  assistantDisplayName?: string;
  teamId?: string;
  teamName?: string;
  isFocused: boolean;
  onFocus: () => void;
  currentProject: ProjectInfo | null;
  onSnapshot: (snapshot: SessionSnapshot | null, actions: SessionActions) => void;
  onCommand: (command: string, args: string) => void;
  runAction: (runId: string, action: 'apply' | 'merge' | 'discard') => Promise<void>;
  openRunWorktree: (runId: string) => Promise<void>;
  handleOpenFileFromPanel: (path: string) => void;
  handleOpenFileFromPanelWithLine: (path: string, line?: number) => void;
  onRevealWorkspace?: () => void;
  onOpenPlanInWorkspace?: () => void;
  onProjectFileEdit?: (edit: FileEdit) => void;
}

export interface SessionViewHandle {
  openFile: (
    relativePath: string,
    content: string,
    language: string,
    options?: Partial<Pick<OpenFile, 'readOnly' | 'source' | 'isPinned'>> & { groupId?: EditorGroup['id'] },
  ) => void;
  switchModel: (modelId: string) => void;
  openRewind: () => void;
}

// ---- Helpers ----

function normalizePath(path: string): string {
  return path.replace(/\\/g, '/').toLowerCase();
}

function generateId(): string {
  return `file_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

// ---- Component ----

export const SessionView = forwardRef<SessionViewHandle, SessionViewProps>(function SessionView(
  {
    sessionId,
    model,
    agentType,
    role,
    assistantDisplayName,
    teamId,
    teamName,
    isFocused,
    onFocus,
    currentProject,
    onSnapshot,
    onCommand,
    runAction,
    openRunWorktree,
    handleOpenFileFromPanel,
    handleOpenFileFromPanelWithLine,
    onRevealWorkspace,
    onOpenPlanInWorkspace,
    onProjectFileEdit,
  },
  ref,
) {
  const {
    messages,
    toolCalls,
    fileEdits,
    runEvents,
    automationSnapshots,
    automationActions,
    automationTraces,
    automationReplayStatus,
    contextUsage,
    checkpoints,
    taskGuidanceItems,
    terminalLogs,
    isRunning,
    isConnected,
    sendMessage,
    queueTaskGuidance,
    applyTaskGuidance,
    deleteTaskGuidance,
    clearTaskGuidance,
    clearSession,
    resetContext,
    compactSession,
    loadCheckpoints,
    rewindToCheckpoint,
    stopRunning,
    retryLast,
    switchModel,
    switchRole,
    executeToolDirect,
    addTerminalLog,
    onToolCallRef,
    onFileEditRef,
    recordFileEdit,
    sendRaw,
    saveInputDraft,
    loadInputDraft,
    clearInputDraft,
    chatMode,
    setChatMode,
    thinkingIntensity,
    setThinkingIntensity,
    planState,
    approvePlan,
    buildPlan,
    pauseBuild,
    endBuild,
    rejectPlan,
    updatePlanDecision,
    submitPlanDecisions,
    suggestAgentSwitch,
    clearSuggestAgentSwitch,
  } = useChatSession(sessionId, model, agentType, role);

  // ---- Send team info to backend on change ----
  useEffect(() => {
    if (!isConnected) return;
    sendRaw({ type: 'set_team', team_id: teamId || null, team_name: teamName || '' });
  }, [isConnected, teamId, teamName, sendRaw]);

  // ---- Per-session derived state ----

  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [latestToolCall, setLatestToolCall] = useState<ToolCall | null>(null);
  const [rewindOpen, setRewindOpen] = useState(false);
  const [editorGroups, setEditorGroups] = useState<EditorGroup[]>([
    { id: 'main', activeFileId: null, openFiles: [] },
  ]);
  const [activeEditorGroup, setActiveEditorGroup] = useState('main');

  // ---- openFile (exposed via ref for sidebar → focused session) ----

  const openFile = useCallback(
    (
      relativePath: string,
      content: string,
      language: string,
      options: Partial<Pick<OpenFile, 'readOnly' | 'source' | 'isPinned'>> & { groupId?: EditorGroup['id'] } = {},
    ) => {
      const normalizedPath = relativePath.replace(/\\/g, '/');
      const openFile: OpenFile = {
        id: generateId(),
        path: normalizedPath,
        name: normalizedPath.split('/').pop() || normalizedPath,
        content,
        language,
        isModified: false,
        source: options.source || 'project',
        readOnly: options.readOnly,
        isPinned: options.isPinned,
      };

      setEditorGroups((prev) => {
        const targetGroupId: EditorGroup['id'] = options.groupId === 'secondary' ? 'secondary' : 'main';
        let groups = prev;
        if (targetGroupId === 'secondary' && !groups.some((group) => group.id === 'secondary')) {
          groups = [...groups, { id: 'secondary', activeFileId: null, openFiles: [] }];
        }
        const groupIdx = Math.max(0, groups.findIndex((group) => group.id === targetGroupId));
        const group = groups[groupIdx];
        const existingIdx = group.openFiles.findIndex(
          (f) => f.path.replace(/\\/g, '/') === normalizedPath,
        );

        let newOpenFiles: OpenFile[];
        let newActiveId: string;

        if (existingIdx >= 0) {
          const existing = group.openFiles[existingIdx];
          newOpenFiles = group.openFiles.map((f, i) =>
            i === existingIdx ? { ...f, ...openFile, id: existing.id } : f,
          );
          newActiveId = existing.id;
        } else {
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

        const newGroups = [...groups];
        newGroups[groupIdx] = { ...group, openFiles: newOpenFiles, activeFileId: newActiveId };
        return newGroups;
      });

      onRevealWorkspace?.();
      if (options.groupId === 'secondary') {
        setActiveEditorGroup('secondary');
      }
    },
    [onRevealWorkspace],
  );

  const openPlanInEditor = useCallback(() => {
    const rawPath = (planState.plan_file_path || 'plan.md').replace(/\\/g, '/');
    const name = rawPath.split('/').pop() || 'plan.md';
    const content = planState.draft || '# Plan\n\nNo markdown body was provided.';
    openFile(rawPath, content, 'markdown', {
      readOnly: true,
      source: 'plan',
      isPinned: true,
    });
    onOpenPlanInWorkspace?.();
    addTerminalLog(`[Plan] Opened ${name} in the editor`);
  }, [addTerminalLog, onOpenPlanInWorkspace, openFile, planState.draft, planState.plan_file_path]);

  const openRewind = useCallback(() => setRewindOpen(true), []);

  useImperativeHandle(ref, () => ({ openFile, switchModel, openRewind }), [openFile, switchModel, openRewind]);

  // ---- Tool call → artifacts observer ----

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
        }

        const item: ArtifactItem = {
          id, type, title: filename, content, url, base64: undefined,
          timestamp: Date.now(), sourceTool: 'file_write',
        };

        setArtifacts((prev) => [...prev, item]);
        if (isFocused) onRevealWorkspace?.();
      }

      if (tc.name === 'shell_execute') {
        const id = `artifact_term_${Date.now()}`;
        const command = tc.args?.command || '';
        const result = tc.result || '';
        setArtifacts((prev) => {
          const existingIdx = prev.findIndex((a) => a.type === 'terminal' && a.sourceTool === 'shell_execute');
          if (existingIdx >= 0) {
            const next = [...prev];
            next[existingIdx] = {
              ...next[existingIdx],
              content: next[existingIdx].content + `\n$ ${command}\n${result}`,
              timestamp: Date.now(),
            };
            return next;
          }
          return [...prev, {
            id, type: 'terminal', title: '终端输出',
            content: `$ ${command}\n${result}`,
            timestamp: Date.now(), sourceTool: 'shell_execute',
          }];
        });
        if (isFocused) onRevealWorkspace?.();
      }
    };
  }, [onToolCallRef, isFocused, onRevealWorkspace]);

  // ---- File edit → editor groups observer ----

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
            return { ...f, content: edit.new_text ?? f.content, isModified: false, hasConflict: false };
          }),
        })),
      );

      if (edit.truncated) {
        addTerminalLog(`[Edit] ${edit.path} changed; full text was too large for inline diff`);
      }
      onProjectFileEdit?.(edit);
    };
    return () => {
      onFileEditRef.current = null;
    };
  }, [onFileEditRef, currentProject, addTerminalLog, onProjectFileEdit]);

  // ---- Editor callbacks ----

  const handleSelectFileInEditor = useCallback((groupId: string, fileId: string) => {
    setEditorGroups((prev) =>
      prev.map((g) => (g.id === groupId ? { ...g, activeFileId: fileId } : g)),
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
      }),
    );
  }, []);

  const handleFileContentChange = useCallback((groupId: string, fileId: string, content: string) => {
    setEditorGroups((prev) =>
      prev.map((g) =>
        g.id === groupId
          ? { ...g, openFiles: g.openFiles.map((f) => f.id === fileId ? { ...f, content, isModified: true } : f) }
          : g,
      ),
    );
  }, []);

  const handleSaveFile = useCallback(async (groupId: string, fileId: string, content: string) => {
    const file = editorGroups.find((g) => g.id === groupId)?.openFiles.find((f) => f.id === fileId);
    if (!file || !currentProject) return;
    if (file.readOnly) {
      addTerminalLog(`[Plan] ${file.name} is read-only`);
      return;
    }
    try {
      const filePath = currentProject.path.replace(/\\/g, '/') + '/' + file.path;
      const res = await fetch(`${API_BASE}/api/file/write`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: filePath, content }),
      });
      const data = await res.json();
      if (data.error) {
        addTerminalLog(`[错误] 保存文件失败: ${data.error}`);
        return;
      }
      setEditorGroups((prev) =>
        prev.map((g) =>
          g.id === groupId
            ? { ...g, openFiles: g.openFiles.map((f) => f.id === fileId ? { ...f, content, isModified: false, hasConflict: false } : f) }
            : g,
        ),
      );
      addTerminalLog(`[系统] 文件已保存: ${file.name}`);
      if (data.file_edit) {
        recordFileEdit(data.file_edit as FileEdit, false);
      }
    } catch (err) {
      addTerminalLog(`[错误] 保存文件出错: ${err}`);
    }
  }, [editorGroups, currentProject, addTerminalLog, recordFileEdit]);

  // ---- Publish snapshot when focused ----

  const sessionProjectPath = agentType === 'coding' ? currentProject?.path ?? null : null;

  const snapshot: SessionSnapshot | null = useMemo(() => {
    if (!isFocused) return null;
    return {
      sessionId,
      projectPath: sessionProjectPath,
      agentType,
      isRunning,
      isConnected,
      chatMode,
      thinkingIntensity,
      planState,
      contextUsage,
      checkpoints,
      suggestAgentSwitch,
      artifacts,
      editorGroups,
      activeEditorGroup,
      latestToolCall,
      fileEdits,
      toolCalls,
      runEvents,
      automationSnapshots,
      automationActions,
      automationTraces,
      automationReplayStatus,
    };
  }, [isFocused, sessionId, sessionProjectPath, agentType, isRunning, isConnected, chatMode, thinkingIntensity, planState,
      contextUsage, checkpoints, suggestAgentSwitch, artifacts, editorGroups, activeEditorGroup, latestToolCall, fileEdits, toolCalls, runEvents,
      automationSnapshots, automationActions, automationTraces, automationReplayStatus]);

  const actions: SessionActions = useMemo(() => ({
    sendMessage,
    clearSession,
    resetContext,
    compactSession,
    loadCheckpoints,
    rewindToCheckpoint,
    stopRunning,
    retryLast,
    switchModel,
    switchRole,
    executeToolDirect,
    addTerminalLog,
    approvePlan,
    buildPlan,
    pauseBuild,
    endBuild,
    rejectPlan,
    updatePlanDecision,
    submitPlanDecisions,
    onSelectFileInEditor: handleSelectFileInEditor,
    onCloseFileInEditor: handleCloseFileInEditor,
    onFileContentChange: handleFileContentChange,
    onSaveFile: handleSaveFile,
    saveInputDraft,
    loadInputDraft,
    clearInputDraft,
    runAction,
    openRunWorktree,
    handleOpenFileFromPanel,
    handleOpenFileFromPanelWithLine,
  }), [
    sendMessage, clearSession, resetContext, compactSession, loadCheckpoints, rewindToCheckpoint,
    stopRunning, retryLast, switchModel, switchRole, executeToolDirect, addTerminalLog,
    approvePlan, buildPlan, pauseBuild, endBuild, rejectPlan, updatePlanDecision, submitPlanDecisions,
    handleSelectFileInEditor, handleCloseFileInEditor, handleFileContentChange, handleSaveFile,
    saveInputDraft, loadInputDraft, clearInputDraft,
    runAction, openRunWorktree, handleOpenFileFromPanel, handleOpenFileFromPanelWithLine,
  ]);

  useEffect(() => {
    onSnapshot(snapshot, actions);
  }, [snapshot, actions, onSnapshot]);

  return (
    <div className="h-full min-h-0 flex flex-col" onClick={onFocus}>
      <ChatPanel
        sessionId={sessionId}
        messages={messages}
        toolCalls={toolCalls}
        fileEdits={fileEdits}
        runEvents={runEvents}
        onSend={sendMessage}
        contextUsage={contextUsage}
        checkpoints={checkpoints}
        taskGuidanceItems={taskGuidanceItems}
        onQueueTaskGuidance={queueTaskGuidance}
        onApplyTaskGuidance={applyTaskGuidance}
        onDeleteTaskGuidance={deleteTaskGuidance}
        onClearTaskGuidance={clearTaskGuidance}
        onCompact={compactSession}
        onClearSession={clearSession}
        onLoadCheckpoints={loadCheckpoints}
        onRewindToCheckpoint={rewindToCheckpoint}
        rewindOpen={rewindOpen}
        onRewindOpenChange={setRewindOpen}
        onStop={stopRunning}
        onRetry={retryLast}
        isRunning={isRunning}
        onDraftSave={saveInputDraft}
        onDraftLoad={loadInputDraft}
        onDraftClear={clearInputDraft}
        chatMode={chatMode}
        onChatModeChange={setChatMode}
        thinkingIntensity={thinkingIntensity}
        onThinkingIntensityChange={setThinkingIntensity}
        planState={planState}
        onApprovePlan={approvePlan}
        onBuildPlan={buildPlan}
        onPauseBuild={pauseBuild}
        onEndBuild={endBuild}
        onRejectPlan={rejectPlan}
        onUpdatePlanDecision={updatePlanDecision}
        onSubmitPlanDecisions={submitPlanDecisions}
        onViewPlan={openPlanInEditor}
        onCommand={onCommand}
        projectOpen={agentType === 'coding' && !!currentProject}
        agentType={agentType}
        assistantDisplayName={assistantDisplayName}
        projectName={agentType === 'coding' ? currentProject?.name : undefined}
      />
    </div>
  );
});
