import React from 'react';
import { FolderOpen, FolderX, GitBranch, GitCommit, Plus, X } from 'lucide-react';
import { ProjectInfo, FileNode } from '../types';
import { FileTree } from './FileTree';

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
  if (!currentProject) {
    return (
      <div className="space-y-3">
        <div className="text-xs text-gray-500 text-center py-4">
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
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
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
      <div className="bg-gray-700/50 rounded p-2.5 space-y-1.5">
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium text-white truncate flex-1" title={currentProject.name}>
            {currentProject.name}
          </div>
          <button
            onClick={onCloseProject}
            className="text-gray-500 hover:text-red-400 ml-1 shrink-0"
            title="关闭项目"
          >
            <FolderX className="w-3 h-3" />
          </button>
        </div>
        <div className="text-[10px] text-gray-500 truncate" title={currentProject.path}>
          {currentProject.path}
        </div>
        {currentProject.git_branch && (
          <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
            <GitBranch className="w-3 h-3" />
            <span>{currentProject.git_branch}</span>
            {(currentProject.git_modified || 0) > 0 && (
              <span className="text-warning">●{currentProject.git_modified}</span>
            )}
            {(currentProject.git_untracked || 0) > 0 && (
              <span className="text-gray-500">+{currentProject.git_untracked}</span>
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
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded text-[10px] bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
        >
          <FolderOpen className="w-3 h-3" />
          打开
        </button>
        <button
          onClick={onOpenModal}
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded text-[10px] bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
        >
          <Plus className="w-3 h-3" />
          新建
        </button>
        <button
          onClick={onRefreshTree}
          className="px-2 py-1 rounded text-[10px] bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
          title="刷新"
        >
          <GitCommit className="w-3 h-3" />
        </button>
      </div>

      {/* 文件树 */}
      <div className="text-xs text-gray-500 uppercase tracking-wider">文件</div>
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
