import React from 'react';
import { ExternalLink, FileWarning, FolderOpen } from 'lucide-react';
import { OpenFile, EditorGroup, ArtifactItem, ArtifactPayload } from '../../types';
import { EditorTabBar } from './EditorTabBar';
import { Breadcrumb } from './Breadcrumb';
import { CodeEditor } from './CodeEditor';
import { OfficeViewer } from '../ArtifactPanel/OfficeViewer';
import { ImageViewer } from '../ArtifactPanel/ImageViewer';
import { API_BASE } from '../../config';

interface EditorPanelProps {
  groups: EditorGroup[];
  activeGroupId: string;
  projectName: string;
  onSelectFile: (groupId: string, fileId: string) => void;
  onCloseFile: (groupId: string, fileId: string) => void;
  onMoveToGroup: (fileId: string, fromGroupId: string, toGroupId: string) => void;
  onSplitEditor: () => void;
  onCloseSplit: () => void;
  onSetActiveGroup: (groupId: string) => void;
  onFileContentChange?: (groupId: string, fileId: string, content: string) => void;
  onSaveFile?: (groupId: string, fileId: string, content: string) => void;
}

export const EditorPanel: React.FC<EditorPanelProps> = ({
  groups,
  activeGroupId,
  projectName,
  onSelectFile,
  onCloseFile,
  onMoveToGroup,
  onSplitEditor,
  onCloseSplit,
  onSetActiveGroup,
  onFileContentChange,
  onSaveFile,
}) => {
  const isSplit = groups.length > 1;

  return (
    <div className="h-full flex bg-app">
      {groups.map((group, idx) => (
        <div
          key={group.id}
          className={`
            flex flex-col
            ${isSplit && idx > 0 ? 'border-l border-border' : ''}
            ${isSplit ? 'w-1/2' : 'flex-1'}
          `}
          onClick={() => onSetActiveGroup(group.id)}
        >
          {/* 面包屑 + 操作栏 */}
          <div className="flex items-center justify-between">
            <div className="flex-1 min-w-0">
              <Breadcrumb
                projectName={projectName}
                filePath={group.openFiles.find(f => f.id === group.activeFileId)?.path || ''}
              />
            </div>
            <div className="h-7 bg-surface border-b border-border shrink-0" />
          </div>

          {/* Tab Bar */}
          <EditorTabBar
            files={group.openFiles}
            activeFileId={group.activeFileId}
            onSelect={(fileId) => onSelectFile(group.id, fileId)}
            onClose={(fileId) => onCloseFile(group.id, fileId)}
          />

          {/* 内容区 */}
          <div className="flex-1 min-h-0 relative">
            <EditorContent
              file={group.openFiles.find(f => f.id === group.activeFileId)}
              groupId={group.id}
              onFileContentChange={onFileContentChange}
              onSaveFile={onSaveFile}
            />
          </div>
        </div>
      ))}
    </div>
  );
};

interface EditorContentProps {
  file?: OpenFile;
  groupId?: string;
  onFileContentChange?: (groupId: string, fileId: string, content: string) => void;
  onSaveFile?: (groupId: string, fileId: string, content: string) => void;
}

function formatBytes(value?: number): string {
  if (!value || value < 0) return '';
  if (value < 1024) return `${value} B`;
  const kb = value / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function assetUrl(url?: string): string | undefined {
  if (!url) return undefined;
  if (url.startsWith('/')) return `${API_BASE}${url}`;
  return url;
}

function artifactToItem(raw: OpenFile['artifact'], fallbackTitle: string): ArtifactItem | null {
  if (!raw) return null;
  const artifact = raw as ArtifactPayload & ArtifactItem & Record<string, any>;
  return {
    id: artifact.id || `editor_artifact_${fallbackTitle}`,
    type: (artifact.type || 'code') as ArtifactItem['type'],
    title: artifact.title || fallbackTitle,
    content: artifact.content,
    url: artifact.url,
    base64: artifact.base64,
    mimeType: artifact.mimeType || artifact.mime_type,
    path: artifact.path,
    caption: artifact.caption,
    timestamp: artifact.timestamp || Date.now(),
    sourceTool: artifact.sourceTool || artifact.source_tool || artifact.source || 'project_file_open',
    size: artifact.size,
    kind: artifact.kind,
    files: artifact.files,
    previews: artifact.previews,
    qaSummary: artifact.qaSummary || artifact.qa_summary,
    engine: artifact.engine,
    officeManifestId: artifact.officeManifestId || artifact.office_manifest_id,
    manifestPath: artifact.manifestPath || artifact.manifest_path,
    manifestUrl: artifact.manifestUrl || artifact.manifest_url,
    viewerManifestUrl: artifact.viewerManifestUrl || artifact.viewer_manifest_url,
    sha256: artifact.sha256,
    renderIssues: artifact.renderIssues || artifact.render_issues,
    availableActions: artifact.availableActions || artifact.available_actions,
    workbook: artifact.workbook,
    presentation: artifact.presentation,
  };
}

const BinaryFileNotice: React.FC<{ file: OpenFile }> = ({ file }) => {
  const path = file.absolutePath || file.path;
  const openPath = async (event: React.MouseEvent) => {
    event.stopPropagation();
    if (!path || !window.electronAPI?.openPath) return;
    await window.electronAPI.openPath(path);
  };
  const revealPath = async (event: React.MouseEvent) => {
    event.stopPropagation();
    if (!path || !window.electronAPI?.revealPath) return;
    await window.electronAPI.revealPath(path);
  };

  return (
    <div className="h-full flex items-center justify-center bg-app p-6">
      <div className="w-full max-w-md rounded border border-border bg-surface p-5 text-center shadow-sm">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded bg-warning/10 text-warning">
          <FileWarning className="h-5 w-5" />
        </div>
        <div className="text-sm font-semibold text-fg">{file.name}</div>
        <div className="mt-1 text-xs text-fg-muted">
          {[file.mimeType, formatBytes(file.size)].filter(Boolean).join(' / ') || 'Binary file'}
        </div>
        <div className="mt-3 text-xs leading-relaxed text-fg-secondary">
          {file.binaryReason || 'This file cannot be displayed in the code editor.'}
        </div>
        <div className="mt-4 flex justify-center gap-2">
          <button
            type="button"
            onClick={openPath}
            className="inline-flex items-center gap-1.5 rounded border border-border bg-app px-3 py-1.5 text-xs text-fg hover:bg-surface-hover disabled:opacity-50"
            disabled={!window.electronAPI?.openPath}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Open
          </button>
          <button
            type="button"
            onClick={revealPath}
            className="inline-flex items-center gap-1.5 rounded border border-border bg-app px-3 py-1.5 text-xs text-fg hover:bg-surface-hover disabled:opacity-50"
            disabled={!window.electronAPI?.revealPath}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Show
          </button>
        </div>
        <div className="mt-4 truncate text-[11px] text-fg-muted" title={path}>
          {path}
        </div>
      </div>
    </div>
  );
};

const EditorContent: React.FC<EditorContentProps> = ({ file, groupId, onFileContentChange, onSaveFile }) => {
  if (!file) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-fg-muted">
        <svg className="w-12 h-12 mb-3 text-fg-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <div className="text-sm">点击文件树中的文件以打开</div>
        <div className="text-xs text-fg-muted mt-1">支持代码编辑、语法高亮、行号显示</div>
      </div>
    );
  }

  if (file.viewerType === 'office') {
    const item = artifactToItem(file.artifact, file.name);
    return item ? <OfficeViewer item={item} /> : <BinaryFileNotice file={{ ...file, binaryReason: file.binaryReason || 'Office preview metadata is unavailable.' }} />;
  }

  if (file.viewerType === 'image') {
    const item = artifactToItem(file.artifact, file.name);
    return <ImageViewer url={assetUrl(item?.url)} base64={item?.base64} />;
  }

  if (file.viewerType === 'binary') {
    return <BinaryFileNotice file={file} />;
  }

  return (
    <CodeEditor
      content={file.content}
      filename={file.name}
      isModified={file.isModified}
      readOnly={file.readOnly}
      onChange={(content) => {
        if (!file.readOnly && groupId && onFileContentChange) {
          onFileContentChange(groupId, file.id, content);
        }
      }}
      onSave={(content) => {
        if (!file.readOnly && groupId && onSaveFile) {
          onSaveFile(groupId, file.id, content);
        }
      }}
    />
  );
};
