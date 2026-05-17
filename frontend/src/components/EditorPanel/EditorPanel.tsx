import React from 'react';
import { OpenFile, EditorGroup } from '../../types';
import { EditorTabBar } from './EditorTabBar';
import { Breadcrumb } from './Breadcrumb';
import { CodeEditor } from './CodeEditor';

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
}

interface EditorContentProps {
  file?: OpenFile;
  groupId?: string;
  onFileContentChange?: (groupId: string, fileId: string, content: string) => void;
  onSaveFile?: (groupId: string, fileId: string, content: string) => void;
}

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

  // 对于图片等二进制文件，显示提示
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].includes(file.language)) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-fg-muted">
        <div className="text-sm">图片文件暂不支持编辑器预览</div>
        <div className="text-xs text-fg-muted mt-1">路径: {file.path}</div>
      </div>
    );
  }

  return (
    <CodeEditor
      content={file.content}
      filename={file.name}
      isModified={file.isModified}
      onChange={(content) => {
        if (groupId && onFileContentChange) {
          onFileContentChange(groupId, file.id, content);
        }
      }}
      onSave={(content) => {
        if (groupId && onSaveFile) {
          onSaveFile(groupId, file.id, content);
        }
      }}
    />
  );
};
