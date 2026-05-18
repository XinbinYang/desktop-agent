import React, { useState, useEffect, useCallback } from 'react';
import { FolderOpen, FolderX, GitBranch, Plus, FileText, Save, Loader, RefreshCw } from 'lucide-react';
import { ProjectInfo, FileNode } from '../types';
import { FileTree, type FileTreeAction } from './FileTree';
import { API_BASE, withAuthQuery } from '../config';

interface ProjectPanelProps {
  currentProject: ProjectInfo | null;
  fileTree: FileNode[];
  expandedPaths: Set<string>;
  loadingPaths?: Set<string>;
  onTogglePath: (path: string) => void;
  onSelectFile: (path: string, type: 'file' | 'dir') => void;
  onFileAction?: (action: FileTreeAction, node: FileNode) => void;
  onOpenFolder: () => void;
  onOpenModal: () => void;
  onCloseProject: () => void;
  onRefreshTree: () => void | Promise<void>;
  isRefreshing?: boolean;
}

export const ProjectPanel: React.FC<ProjectPanelProps> = ({
  currentProject,
  fileTree,
  expandedPaths,
  loadingPaths = new Set(),
  onTogglePath,
  onSelectFile,
  onFileAction,
  onOpenFolder,
  onOpenModal,
  onCloseProject,
  onRefreshTree,
  isRefreshing = false,
}) => {
  const [showRules, setShowRules] = useState(false);
  const [rulesContent, setRulesContent] = useState('');
  const [rulesLoaded, setRulesLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadRules = useCallback(async () => {
    if (!currentProject) return;
    try {
      const res = await fetch(withAuthQuery(`${API_BASE}/api/projects/rules`));
      const data = await res.json();
      setRulesContent(data.content || '');
      setRulesLoaded(true);
    } catch {
      setRulesContent('');
      setRulesLoaded(false);
    }
  }, [currentProject]);

  const saveRules = useCallback(async () => {
    if (!currentProject) return;
    setSaving(true);
    try {
      await fetch(`${API_BASE}/api/projects/rules`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: rulesContent }),
      });
    } finally {
      setSaving(false);
    }
  }, [currentProject, rulesContent]);

  useEffect(() => {
    if (showRules && !rulesLoaded) {
      loadRules();
    }
  }, [showRules, rulesLoaded, loadRules]);

  if (!currentProject) {
    return (
      <div className="space-y-3">
        <div className="text-xs text-fg-muted text-center py-4">
          没有打开的项目
        </div>
        <button
          type="button"
          onClick={onOpenFolder}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors"
        >
          <FolderOpen className="w-3.5 h-3.5" />
          打开文件夹
        </button>
        <button
          type="button"
          onClick={onOpenModal}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs bg-surface-alt text-fg-secondary hover:bg-surface-hover transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          新建 / Clone 项目
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full space-y-3">
      <div className="bg-surface-alt/50 rounded p-2.5 space-y-1.5">
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium text-fg truncate flex-1" title={currentProject.name}>
            {currentProject.name}
          </div>
          <div className="flex items-center gap-1 ml-1 shrink-0">
            <button
              type="button"
              onClick={() => { void onRefreshTree(); }}
              disabled={isRefreshing}
              className="text-fg-muted hover:text-fg disabled:opacity-50 disabled:cursor-not-allowed"
              title="刷新项目文件"
              aria-label="刷新项目文件"
            >
              <RefreshCw className={`w-3 h-3 ${isRefreshing ? 'animate-spin' : ''}`} />
            </button>
            <button
              type="button"
              onClick={onCloseProject}
              className="text-fg-muted hover:text-danger"
              title="关闭项目"
              aria-label="关闭项目"
            >
              <FolderX className="w-3 h-3" />
            </button>
          </div>
        </div>
        <div className="text-[10px] text-fg-muted truncate" title={currentProject.path}>
          {currentProject.path}
        </div>
        {currentProject.git_branch && (
          <div className="flex items-center gap-1.5 text-[10px] text-fg-secondary">
            <GitBranch className="w-3 h-3" />
            <span>{currentProject.git_branch}</span>
            {(currentProject.git_modified || 0) > 0 && (
              <span className="text-warning">●{currentProject.git_modified}</span>
            )}
            {(currentProject.git_untracked || 0) > 0 && (
              <span className="text-fg-muted">+{currentProject.git_untracked}</span>
            )}
            {(currentProject.git_ahead || 0) > 0 && (
              <span className="text-success">↑{currentProject.git_ahead}</span>
            )}
            {(currentProject.git_behind || 0) > 0 && (
              <span className="text-info">↓{currentProject.git_behind}</span>
            )}
          </div>
        )}
      </div>

      <div className="flex gap-1">
        <button
          type="button"
          onClick={onOpenFolder}
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded text-[10px] bg-surface-alt text-fg-secondary hover:bg-surface-hover transition-colors"
        >
          <FolderOpen className="w-3 h-3" />
          打开
        </button>
        <button
          type="button"
          onClick={onOpenModal}
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded text-[10px] bg-surface-alt text-fg-secondary hover:bg-surface-hover transition-colors"
        >
          <Plus className="w-3 h-3" />
          新建
        </button>
      </div>

      <button
        type="button"
        onClick={() => { setShowRules(!showRules); setRulesLoaded(false); }}
        className={`w-full flex items-center justify-center gap-1 px-2 py-1 rounded text-[10px] transition-colors ${
          showRules ? 'bg-accent/10 text-accent' : 'bg-surface-alt text-fg-secondary hover:bg-surface-hover'
        }`}
        title="编辑项目规则 (.desktop-agent.md)"
      >
        <FileText className="w-3 h-3" />
        {showRules ? '隐藏规则' : '编辑规则'}
      </button>

      {showRules && (
        <div className="space-y-2 border-t border-border pt-2">
          <div className="text-[10px] text-fg-muted">
            项目规则（.desktop-agent.md）会被 Agent 自动读取并遵守
          </div>
          <textarea
            value={rulesContent}
            onChange={(e) => setRulesContent(e.target.value)}
            className="w-full h-32 p-2 rounded text-xs bg-surface border border-border text-fg resize-y font-mono"
            placeholder="# 项目规则示例&#10;- 所有 API 路由放在 src/routes/&#10;- 使用 zod 做参数校验&#10;- 测试文件以 .test.ts 结尾"
            spellCheck={false}
          />
          <button
            type="button"
            onClick={saveRules}
            disabled={saving}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors disabled:opacity-50"
          >
            {saving ? <Loader className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
            保存规则
          </button>
        </div>
      )}

      <div className="text-xs font-medium text-fg-muted">文件</div>
      <div className="flex-1 overflow-y-auto min-h-0">
        <FileTree
          nodes={fileTree}
          onSelect={onSelectFile}
          expandedPaths={expandedPaths}
          onToggle={onTogglePath}
          loadingPaths={loadingPaths}
          onAction={onFileAction}
        />
      </div>
    </div>
  );
};
