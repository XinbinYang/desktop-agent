import React, { useState } from 'react';
import { Folder, FolderOpen, FileCode, FileJson, FileText, FileImage, File } from 'lucide-react';
import { FileNode } from '../types';

interface FileTreeProps {
  nodes: FileNode[];
  onSelect: (path: string, type: 'file' | 'dir') => void;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
}

const getFileIcon = (node: FileNode, isExpanded: boolean) => {
  if (node.type === 'dir') {
    return isExpanded ? FolderOpen : Folder;
  }
  const ext = node.extension?.toLowerCase();
  switch (ext) {
    case 'js': case 'jsx': case 'ts': case 'tsx':
    case 'py': case 'java': case 'cpp': case 'c': case 'go': case 'rs':
      return FileCode;
    case 'json':
      return FileJson;
    case 'md': case 'txt': case 'rst':
      return FileText;
    case 'png': case 'jpg': case 'jpeg': case 'gif': case 'svg': case 'webp':
      return FileImage;
    default:
      return File;
  }
};

const FileTreeNode: React.FC<{
  node: FileNode;
  depth: number;
  onSelect: (path: string, type: 'file' | 'dir') => void;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
}> = ({ node, depth, onSelect, expandedPaths, onToggle }) => {
  const isExpanded = expandedPaths.has(node.path);
  const Icon = getFileIcon(node, isExpanded);

  return (
    <div>
      <div
        className={`flex items-center gap-1.5 px-1 py-0.5 rounded text-xs cursor-pointer transition-colors ${
          node.type === 'dir' ? 'text-fg-secondary hover:bg-surface-hover' : 'text-fg-secondary hover:bg-surface-hover hover:text-fg'
        }`}
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
        onClick={() => {
          if (node.type === 'dir') {
            onToggle(node.path);
          }
          onSelect(node.path, node.type);
        }}
      >
        <Icon className="w-3.5 h-3.5 shrink-0" />
        <span className="truncate">{node.name}</span>
      </div>
      {node.type === 'dir' && isExpanded && node.children && (
        <div>
          {node.children.map(child => (
            <FileTreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelect={onSelect}
              expandedPaths={expandedPaths}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const FileTree: React.FC<FileTreeProps> = ({ nodes, onSelect, expandedPaths, onToggle }) => {
  if (nodes.length === 0) {
    return (
      <div className="text-xs text-fg-muted text-center py-4">
        暂无文件
      </div>
    );
  }

  return (
    <div className="space-y-0.5">
      {nodes.map(node => (
        <FileTreeNode
          key={node.path}
          node={node}
          depth={0}
          onSelect={onSelect}
          expandedPaths={expandedPaths}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
};
