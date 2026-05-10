import React from 'react';
import { OpenFile } from '../../types';

interface EditorTabBarProps {
  files: OpenFile[];
  activeFileId: string | null;
  onSelect: (fileId: string) => void;
  onClose: (fileId: string) => void;
  onPin?: (fileId: string) => void;
}

export const EditorTabBar: React.FC<EditorTabBarProps> = ({
  files,
  activeFileId,
  onSelect,
  onClose,
  onPin,
}) => {
  const handleMouseDown = (e: React.MouseEvent, fileId: string) => {
    // 中键关闭
    if (e.button === 1) {
      e.preventDefault();
      onClose(fileId);
    }
  };

  if (files.length === 0) {
    return (
      <div className="h-8 bg-gray-800 border-b border-gray-700 flex items-center px-2 text-[11px] text-gray-500">
        点击文件树中的文件以打开
      </div>
    );
  }

  return (
    <div className="h-8 bg-gray-800 border-b border-gray-700 flex items-center overflow-x-auto scrollbar-hide">
      {files.map((file) => {
        const isActive = file.id === activeFileId;
        return (
          <div
            key={file.id}
            onClick={() => onSelect(file.id)}
            onMouseDown={(e) => handleMouseDown(e, file.id)}
            className={`
              group flex items-center gap-1.5 px-3 h-full min-w-[80px] max-w-[180px] cursor-pointer
              border-r border-gray-700 select-none text-[11px] whitespace-nowrap
              transition-colors duration-75
              ${isActive ? 'bg-gray-700 text-gray-100' : 'bg-gray-800 text-gray-400 hover:bg-gray-750 hover:text-gray-200'}
            `}
            title={file.path}
          >
            {/* 文件类型图标 */}
            <FileIcon lang={file.language} />
            
            {/* 文件名 */}
            <span className="truncate flex-1">{file.name}</span>
            
            {/* 未保存标记 */}
            {file.isModified && (
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" title="文件已被修改" />
            )}
            
            {/* 固定标记 */}
            {file.isPinned && (
              <svg className="w-3 h-3 text-gray-400 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path d="M10 2a1 1 0 011 1v1.323l3.954 1.582 1.699-3.181a1 1 0 011.827 1.035L17.475 7.5H20a1 1 0 011 1v2a1 1 0 01-1 1h-2.525l-.995 1.739a1 1 0 01-1.827-1.035L14.954 10.5 11 8.918V18a1 1 0 11-2 0V8.918l-3.954 1.582-1.699-3.181a1 1 0 011.827-1.035L5.525 10.5H3a1 1 0 01-1-1v-2a1 1 0 011-1h2.525l.995-1.739a1 1 0 011.827 1.035L8.046 5.905 12 4.323V3a1 1 0 011-1z" />
              </svg>
            )}
            
            {/* 关闭按钮 */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onClose(file.id);
              }}
              className={`
                ml-0.5 rounded p-0.5 opacity-0 group-hover:opacity-100
                hover:bg-gray-600 transition-opacity
                ${isActive ? 'opacity-100' : ''}
              `}
              title="关闭"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        );
      })}
    </div>
  );
};

function FileIcon({ lang }: { lang: string }) {
  // 根据语言返回颜色
  const colorMap: Record<string, string> = {
    python: 'text-yellow-400',
    javascript: 'text-yellow-300',
    typescript: 'text-blue-400',
    jsx: 'text-cyan-400',
    tsx: 'text-blue-400',
    css: 'text-blue-300',
    scss: 'text-pink-400',
    html: 'text-orange-400',
    markdown: 'text-gray-300',
    json: 'text-yellow-200',
    yaml: 'text-red-300',
    bash: 'text-green-400',
    rust: 'text-orange-500',
    go: 'text-cyan-400',
    java: 'text-red-400',
    cpp: 'text-blue-500',
    c: 'text-blue-600',
  };
  const color = colorMap[lang] || 'text-gray-400';

  return (
    <svg className={`w-3.5 h-3.5 shrink-0 ${color}`} fill="currentColor" viewBox="0 0 20 20">
      <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
    </svg>
  );
}
