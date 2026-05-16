import React, { useState, useEffect, useCallback } from 'react';
import { FolderOpen, FolderX, GitBranch, GitCommit, Plus, X, FileText, Save, Loader } from 'lucide-react';
import { ProjectInfo, FileNode } from '../types';
import { FileTree } from './FileTree';
import { API_BASE, withAuthQuery } from '../config';

interface ProjectPanelProps {
  currentProject: ProjectInfo | null;
  fileTree: FileNode[];
  expandedPaths: Set<string>;
  onTogglePath: (path: string) => void;
  onSelectFile: (path: string, type: 'file' | 'dir') => void;
  onOpenFolder: () => void;
  onOpenModal: () => void;
  onCloseProject: () => void;
  onRefreshTree: () => void;
}

export const ProjectPanel: React.FC<ProjectPanelProps> = ({
  currentProject,
  fileTree,
  expandedPaths,
  onTogglePath,
  onSelectFile,
  onOpenFolder,
  onOpenModal,
  onCloseProject,
  onRefreshTree,
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
          onClick={onOpenFolder}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors"
        >
          <FolderOpen className="w-3.5 h-3.5" />
          打开文件夹
        </button>
        <button
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
      {/* 项目信息卡片 */}
      <div className="bg-surface-alt/50 rounded p-2.5 space-y-1.5">
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium text-white truncate flex-1" title={currentProject.name}>
            {currentProject.name}
          </div>
          <button
            onClick={onCloseProject}
            className="text-fg-muted hover:text-red-400 ml-1 shrink-0"
            title="关闭项目"
          >
            <FolderX className="w-3 h-3" />
          </button>
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

      {/* 操作按钮 */}
      <div className="flex gap-1">
        <button
          onClick={onOpenFolder}
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded text-[10px] bg-surface-alt text-fg-secondary hover:bg-surface-hover transition-colors"
        >
          <FolderOpen className="w-3 h-3" />
          打开
        </button>
        <button
          onClick={onOpenModal}
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded text-[10px] bg-surface-alt text-fg-secondary hover:bg-surface-hover transition-colors"
        >
          <Plus className="w-3 h-3" />
          新建
        </button>
        <button
          onClick={onRefreshTree}
          className="px-2 py-1 rounded text-[10px] bg-surface-alt text-fg-secondary hover:bg-surface-hover transition-colors"
          title="刷新"
        >
          <GitCommit className="w-3 h-3" />
        </button>
      </div>

      {/* 规则文件按钮 */}
      <button
        onClick={() => { setShowRules(!showRules); setRulesLoaded(false); }}
        className={`w-full flex items-center justify-center gap-1 px-2 py-1 rounded text-[10px] transition-colors ${
          showRules ? 'bg-accent/10 text-accent' : 'bg-surface-alt text-fg-secondary hover:bg-surface-hover'
        }`}
        title="编辑项目规则 (.desktop-agent.md)"
      >
        <FileText className="w-3 h-3" />
        {showRules ? '隐藏规则' : '编辑规则'}
      </button>

      {/* 规则编辑器 */}
      {showRules && (
        <div className="space-y-2 border-t border-border pt-2">
          <div className="text-[10px] text-fg-muted">
            项目规则（.desktop-agent.md）— 类似 CLAUDE.md，Agent 会自动读取并遵守
          </div>
          <textarea
            value={rulesContent}
            onChange={(e) => setRulesContent(e.target.value)}
            className="w-full h-32 p-2 rounded text-xs bg-surface border border-border text-fg resize-y font-mono"
            placeholder="# 项目规则示例&#10;- 所有 API 路由放在 src/routes/&#10;- 使用 zod 做参数校验&#10;- 测试文件以 .test.ts 结尾"
            spellCheck={false}
          />
          <button
            onClick={saveRules}
            disabled={saving}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors disabled:opacity-50"
          >
            {saving ? <Loader className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
            保存规则
          </button>
        </div>
      )}

      {/* 文件树 */}
      <div className="text-xs text-fg-muted uppercase tracking-wider">文件</div>
      <div className="flex-1 overflow-y-auto min-h-0">
        <FileTree
          nodes={fileTree}
          onSelect={onSelectFile}
          expandedPaths={expandedPaths}
          onToggle={onTogglePath}
        />
      </div>
    </div>
  );
};
