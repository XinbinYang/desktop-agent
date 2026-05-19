import React, { useEffect, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  File,
  FileCode,
  FileImage,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
  PanelRightOpen,
  Pencil,
  Play,
  Terminal,
  TestTube2,
  Trash2,
} from 'lucide-react';
import { FileNode } from '../types';

export type FileTreeAction =
  | 'open'
  | 'open_side'
  | 'open_external'
  | 'reveal'
  | 'open_terminal'
  | 'copy_path'
  | 'copy_relative_path'
  | 'rename'
  | 'delete'
  | 'run_file'
  | 'run_tests'
  | 'toggle';

interface FileTreeProps {
  nodes: FileNode[];
  onSelect: (path: string, type: 'file' | 'dir') => void;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  loadingPaths?: Set<string>;
  onAction?: (action: FileTreeAction, node: FileNode) => void;
}

const RUN_FILE_EXTENSIONS = new Set(['py', 'js', 'mjs', 'cjs', 'ps1', 'bat', 'cmd']);
const JS_TEST_EXTENSIONS = new Set(['js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs']);

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

const isRunnableFile = (node: FileNode) => (
  node.type === 'file' && RUN_FILE_EXTENSIONS.has((node.extension || '').toLowerCase())
);

const isTestFile = (node: FileNode) => {
  if (node.type !== 'file') return false;
  const name = node.name.toLowerCase();
  const ext = (node.extension || '').toLowerCase();
  if (ext === 'py') return name.startsWith('test_') || name.endsWith('_test.py');
  return JS_TEST_EXTENSIONS.has(ext) && (
    name.includes('.test.') ||
    name.includes('.spec.') ||
    node.path.toLowerCase().includes('/__tests__/')
  );
};

const MenuSeparator = () => <div className="h-px bg-border mx-2 my-1" />;

const MenuItem: React.FC<{
  icon: React.ReactNode;
  label: string;
  destructive?: boolean;
  onClick: () => void;
}> = ({ icon, label, destructive = false, onClick }) => (
  <button
    type="button"
    className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs outline-none ${
      destructive
        ? 'text-danger hover:bg-danger/10'
        : 'text-fg-secondary hover:bg-surface-hover hover:text-fg'
    }`}
    onClick={(event) => {
      event.preventDefault();
      event.stopPropagation();
      onClick();
    }}
  >
    <span className="w-3.5 h-3.5 shrink-0 flex items-center justify-center">{icon}</span>
    <span className="truncate">{label}</span>
  </button>
);

const FileTreeNode: React.FC<{
  node: FileNode;
  depth: number;
  onSelect: (path: string, type: 'file' | 'dir') => void;
  expandedPaths: Set<string>;
  onToggle: (path: string) => void;
  loadingPaths?: Set<string>;
  onContextMenu?: (event: React.MouseEvent, node: FileNode) => void;
}> = ({ node, depth, onSelect, expandedPaths, onToggle, loadingPaths = new Set(), onContextMenu }) => {
  const isExpanded = expandedPaths.has(node.path);
  const isLoading = loadingPaths.has(node.path);
  const canExpand = node.type === 'dir' && (node.has_children !== false || (node.children?.length || 0) > 0);
  const Icon = getFileIcon(node, isExpanded);

  return (
    <div>
      <button
        type="button"
        className={`w-full flex items-center gap-1 px-1 py-0.5 rounded text-xs cursor-pointer text-left transition-colors ${
          node.type === 'dir' ? 'text-fg-secondary hover:bg-surface-hover' : 'text-fg-secondary hover:bg-surface-hover hover:text-fg'
        }`}
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
        onClick={() => {
          if (node.type === 'dir') {
            onToggle(node.path);
          } else {
            onSelect(node.path, node.type);
          }
        }}
        onContextMenu={(event) => {
          if (!onContextMenu) return;
          event.preventDefault();
          event.stopPropagation();
          onContextMenu(event, node);
        }}
      >
        {node.type === 'dir' ? (
          <span className="w-3.5 h-3.5 shrink-0 flex items-center justify-center">
            {isLoading ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : canExpand ? (
              isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />
            ) : null}
          </span>
        ) : (
          <span className="w-3.5 h-3.5 shrink-0" />
        )}
        <Icon className="w-3.5 h-3.5 shrink-0" />
        <span className="truncate min-w-0">{node.name}</span>
      </button>
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
              loadingPaths={loadingPaths}
              onContextMenu={onContextMenu}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const FileTree: React.FC<FileTreeProps> = ({
  nodes,
  onSelect,
  expandedPaths,
  onToggle,
  loadingPaths = new Set(),
  onAction,
}) => {
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; node: FileNode } | null>(null);

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    window.addEventListener('click', close);
    window.addEventListener('keydown', closeOnEscape);
    window.addEventListener('scroll', close, true);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('keydown', closeOnEscape);
      window.removeEventListener('scroll', close, true);
    };
  }, [contextMenu]);

  const emitAction = (action: FileTreeAction, node: FileNode) => {
    onAction?.(action, node);
    setContextMenu(null);
  };

  const handleNodeContextMenu = (event: React.MouseEvent, node: FileNode) => {
    setContextMenu({ x: event.clientX, y: event.clientY, node });
  };

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
          loadingPaths={loadingPaths}
          onContextMenu={onAction ? handleNodeContextMenu : undefined}
        />
      ))}
      {contextMenu && onAction && (
        <FileContextMenu
          node={contextMenu.node}
          x={contextMenu.x}
          y={contextMenu.y}
          isExpanded={expandedPaths.has(contextMenu.node.path)}
          onAction={(action) => emitAction(action, contextMenu.node)}
        />
      )}
    </div>
  );
};

const FileContextMenu: React.FC<{
  node: FileNode;
  x: number;
  y: number;
  isExpanded: boolean;
  onAction: (action: FileTreeAction) => void;
}> = ({ node, x, y, isExpanded, onAction }) => {
  const isDir = node.type === 'dir';
  const canExpand = isDir && (node.has_children !== false || (node.children?.length || 0) > 0);
  const left = Math.min(x, Math.max(8, window.innerWidth - 230));
  const top = Math.min(y, Math.max(8, window.innerHeight - 360));
  const hasRunActions = isRunnableFile(node) || isDir || isTestFile(node);

  return (
    <>
      <div className="fixed inset-0 z-40" onContextMenu={(event) => event.preventDefault()} />
      <div
        role="menu"
        aria-label="文件操作菜单"
        className="fixed z-50 min-w-[210px] max-w-[260px] bg-surface-elevated border border-border rounded-md shadow-xl py-1"
        style={{ left, top }}
        onClick={(event) => event.stopPropagation()}
        onContextMenu={(event) => event.preventDefault()}
      >
        {!isDir && (
          <>
            <MenuItem icon={<FileText className="w-3.5 h-3.5" />} label="打开" onClick={() => onAction('open')} />
            <MenuItem icon={<PanelRightOpen className="w-3.5 h-3.5" />} label="打开到侧边" onClick={() => onAction('open_side')} />
            <MenuItem icon={<ExternalLink className="w-3.5 h-3.5" />} label="系统打开" onClick={() => onAction('open_external')} />
            <MenuSeparator />
          </>
        )}
        {isDir && canExpand && (
          <>
            <MenuItem icon={isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />} label={isExpanded ? '折叠' : '展开'} onClick={() => onAction('toggle')} />
            <MenuSeparator />
          </>
        )}
        <MenuItem icon={<FolderOpen className="w-3.5 h-3.5" />} label="在资源管理器中显示" onClick={() => onAction('reveal')} />
        <MenuItem icon={<Terminal className="w-3.5 h-3.5" />} label="在终端中打开" onClick={() => onAction('open_terminal')} />
        <MenuSeparator />
        <MenuItem icon={<Copy className="w-3.5 h-3.5" />} label="复制路径" onClick={() => onAction('copy_path')} />
        <MenuItem icon={<Copy className="w-3.5 h-3.5" />} label="复制相对路径" onClick={() => onAction('copy_relative_path')} />
        {hasRunActions && <MenuSeparator />}
        {isRunnableFile(node) && (
          <MenuItem icon={<Play className="w-3.5 h-3.5" />} label="运行文件" onClick={() => onAction('run_file')} />
        )}
        {(isDir || isTestFile(node)) && (
          <MenuItem icon={<TestTube2 className="w-3.5 h-3.5" />} label={isDir ? '运行该目录测试' : '运行测试'} onClick={() => onAction('run_tests')} />
        )}
        <MenuSeparator />
        <MenuItem icon={<Pencil className="w-3.5 h-3.5" />} label="重命名" onClick={() => onAction('rename')} />
        <MenuItem icon={<Trash2 className="w-3.5 h-3.5" />} label="删除" destructive onClick={() => onAction('delete')} />
      </div>
    </>
  );
};
