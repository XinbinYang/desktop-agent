import React, { useEffect, useState } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { FileEdit } from '../types';
import { getLangFromFilename } from '../lib/language';
import { FileEditView } from './FileEditView';

interface ChangesPanelProps {
  edits: FileEdit[];
  onOpenFile?: (path: string) => void;
}

function shortPath(path: string): string {
  const normalized = path.replace(/\\/g, '/');
  const parts = normalized.split('/');
  return parts.slice(-2).join('/');
}

export const ChangesPanel: React.FC<ChangesPanelProps> = ({ edits, onOpenFile }) => {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    if (edits.length > 0) {
      setActiveIndex(edits.length - 1);
    }
  }, [edits.length]);

  const active = edits[activeIndex];

  if (edits.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-fg-muted">
        No file edits yet
      </div>
    );
  }

  return (
    <div className="h-full flex bg-gray-900">
      <div className="w-52 border-r border-gray-700 overflow-y-auto shrink-0">
        {edits.map((edit, index) => (
          <button
            key={`${edit.path}-${edit.timestamp || index}`}
            type="button"
            onClick={() => setActiveIndex(index)}
            className={`w-full px-3 py-2 text-left border-b border-gray-800 hover:bg-gray-800 transition-colors ${
              activeIndex === index ? 'bg-gray-800 text-gray-100' : 'text-gray-400'
            }`}
          >
            <div className="text-xs truncate">{shortPath(edit.path)}</div>
            <div className="mt-1 flex items-center gap-2 text-[11px]">
              <span className="text-green-400">+{edit.stats?.added || 0}</span>
              <span className="text-red-400">-{edit.stats?.removed || 0}</span>
              {edit.truncated && <span className="text-yellow-400">large</span>}
            </div>
          </button>
        ))}
      </div>
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="h-8 border-b border-gray-700 bg-gray-800 flex items-center justify-between px-3">
          <div className="text-xs text-gray-300 truncate">{active?.path}</div>
          {active && onOpenFile && (
            <button
              type="button"
              onClick={() => onOpenFile(active.path)}
              className="text-[11px] text-blue-300 hover:text-blue-200 px-2 py-0.5 rounded hover:bg-gray-700"
            >
              Open
            </button>
          )}
        </div>
        <div className="flex-1 min-h-0">
          {active?.old_text != null && active?.new_text != null && !active.truncated ? (
            <DiffEditor
              height="100%"
              language={getLangFromFilename(active.path, 'monaco')}
              original={active.old_text}
              modified={active.new_text}
              theme="vs-dark"
              options={{
                readOnly: true,
                renderSideBySide: true,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                automaticLayout: true,
                fontSize: 12,
                wordWrap: 'on',
              }}
            />
          ) : active ? (
            <div className="h-full overflow-auto p-3">
              <FileEditView edit={active} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};
