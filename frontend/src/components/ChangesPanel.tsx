import React, { useEffect, useState, useCallback } from 'react';
import { DiffEditor } from '@monaco-editor/react';
import { X, XCircle } from 'lucide-react';
import { FileEdit } from '../types';
import { getLangFromFilename } from '../lib/language';
import { ensureMonacoThemes, getMonacoThemeName } from '../lib/monacoTheme';
import { useTheme } from '../hooks/useTheme';
import { FileEditView } from './FileEditView';
import { API_BASE } from '../config';
import { RevealPathButton } from './RevealPathAction';

interface ChangesPanelProps {
  edits: FileEdit[];
  onOpenFile?: (path: string) => void;
  projectPath?: string | null;
}

type EditStatus = 'accepted' | 'rejected';

function shortPath(path: string): string {
  const normalized = path.replace(/\\/g, '/');
  const parts = normalized.split('/');
  return parts.slice(-2).join('/');
}

export const ChangesPanel: React.FC<ChangesPanelProps> = ({ edits, onOpenFile, projectPath }) => {
  const [activeIndex, setActiveIndex] = useState(0);
  const [statuses, setStatuses] = useState<Record<number, EditStatus>>({});
  const [reverting, setReverting] = useState(false);
  const { resolved } = useTheme();
  const monacoTheme = getMonacoThemeName(resolved);

  useEffect(() => {
    setStatuses((prev) => {
      const next: Record<number, EditStatus> = {};
      let changed = Object.keys(prev).length !== edits.length;
      edits.forEach((_, index) => {
        next[index] = prev[index] || 'accepted';
        if (next[index] !== prev[index]) changed = true;
      });
      return changed ? next : prev;
    });

    if (edits.length > 0) {
      setActiveIndex(edits.length - 1);
    }
  }, [edits]);

  const active = edits[activeIndex];
  const activeStatus = statuses[activeIndex] || 'accepted';

  const rejectEdit = useCallback(async (index: number) => {
    const edit = edits[index];
    if (!edit || edit.old_text == null) return;
    setReverting(true);
    try {
      const response = await fetch(`${API_BASE}/api/file/revert`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: edit.path, old_content: edit.old_text }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || data?.error) {
        throw new Error(typeof data?.error === 'string' ? data.error : 'Revert failed');
      }
      setStatuses((prev) => ({ ...prev, [index]: 'rejected' }));
    } catch (err) {
      console.error('Revert failed:', err);
    } finally {
      setReverting(false);
    }
  }, [edits]);

  const rejectAll = useCallback(async () => {
    for (let i = 0; i < edits.length; i++) {
      if ((statuses[i] || 'accepted') !== 'rejected') {
        await rejectEdit(i);
      }
    }
  }, [edits, rejectEdit, statuses]);

  if (edits.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-fg-muted">
        No file edits yet
      </div>
    );
  }

  const acceptedCount = edits.filter((_, i) => (statuses[i] || 'accepted') === 'accepted').length;
  const rejectedCount = edits.length - acceptedCount;

  return (
    <div className="h-full flex flex-col bg-app">
      {/* Toolbar */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-border bg-surface/50">
        <span className="text-[10px] text-fg-muted mr-auto">
          {acceptedCount} accepted{rejectedCount > 0 ? ` · ${rejectedCount} reverted` : ''}
        </span>
        <button
          type="button"
          onClick={rejectAll}
          disabled={reverting}
          className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
        >
          <XCircle className="w-3 h-3" />
          Revert All
        </button>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Sidebar list */}
        <div className="w-52 border-r border-border overflow-y-auto shrink-0">
          {edits.map((edit, index) => {
            const status = statuses[index] || 'pending';
            const isActive = activeIndex === index;
            return (
              <button
                key={`${edit.path}-${edit.timestamp || index}`}
                type="button"
                onClick={() => setActiveIndex(index)}
                className={`w-full px-3 py-2 text-left border-b border-border hover:bg-surface transition-colors ${
                  isActive ? 'bg-surface' : ''
                } ${status === 'rejected' ? 'opacity-40' : ''}`}
              >
                <div className="flex items-center gap-1.5">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    status === 'accepted' ? 'bg-green-400'
                    : 'bg-red-400'
                  }`} />
                  <span className="text-xs truncate text-fg-secondary">{shortPath(edit.path)}</span>
                </div>
                <div className="mt-1 flex items-center gap-2 text-[11px]">
                  <span className="text-green-400">+{edit.stats?.added || 0}</span>
                  <span className="text-red-400">-{edit.stats?.removed || 0}</span>
                  {edit.truncated && <span className="text-yellow-400">large</span>}
                </div>
              </button>
            );
          })}
        </div>

        {/* Diff view */}
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="h-8 border-b border-border bg-surface flex items-center justify-between px-3">
            <div className="flex items-center gap-2">
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                activeStatus === 'accepted' ? 'bg-green-500/10 text-green-400'
                : 'bg-red-500/10 text-red-400'
              }`}>
                {activeStatus}
              </span>
              <span className="text-xs text-fg-secondary truncate">{active?.path}</span>
            </div>
            <div className="flex items-center gap-1">
              {active && activeStatus !== 'rejected' && (
                <button
                  type="button"
                  onClick={() => rejectEdit(activeIndex)}
                  disabled={reverting || active.old_text == null}
                  className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50"
                >
                  <X className="w-3 h-3" />
                  Revert
                </button>
              )}
              {active && onOpenFile && (
                <button
                  type="button"
                  onClick={() => onOpenFile(active.path)}
                  className="text-[10px] text-blue-300 hover:text-blue-200 px-2 py-0.5 rounded hover:bg-surface-hover ml-2"
                >
                  Open
                </button>
              )}
              {active && (
                <RevealPathButton
                  path={active.path}
                  projectPath={projectPath}
                  className="h-6 w-6"
                />
              )}
            </div>
          </div>
          <div className="flex-1 min-h-0">
            {active?.old_text != null && active?.new_text != null && !active.truncated ? (
              <DiffEditor
                height="100%"
                language={getLangFromFilename(active.path, 'monaco')}
                original={active.old_text}
                modified={active.new_text}
                theme={monacoTheme}
                beforeMount={ensureMonacoThemes}
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
                <FileEditView edit={active} projectPath={projectPath} />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
};
