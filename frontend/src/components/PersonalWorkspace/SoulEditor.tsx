import React, { useState, useEffect, useCallback } from 'react';
import { Save, RefreshCw, Loader2 } from 'lucide-react';
import { API_BASE } from '../../config';
import { cn } from '../ui/cn';

const FILES = [
  { name: 'SOUL.md', label: 'SOUL', desc: '人格核心' },
  { name: 'INNER.md', label: 'INNER', desc: '内在世界' },
  { name: 'IDENTITY.md', label: 'IDENTITY', desc: '身份信息' },
  { name: 'USER.md', label: 'USER', desc: '用户画像' },
];

interface FileState {
  content: string;
  loading: boolean;
  saving: boolean;
  error: string | null;
}

async function loadFile(filename: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/agents/personal/files/${encodeURIComponent(filename)}`);
  if (!res.ok) throw new Error(`Failed to load: ${res.status}`);
  const data = await res.json();
  return data.content || '';
}

async function saveFile(filename: string, content: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/agents/personal/files/${encodeURIComponent(filename)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed to save: ${res.status}`);
}

export const SoulEditor: React.FC = () => {
  const [activeFile, setActiveFile] = useState('SOUL.md');
  const [files, setFiles] = useState<Record<string, FileState>>({});

  const current = files[activeFile] || { content: '', loading: true, saving: false, error: null };

  const fetchFile = useCallback(async (filename: string) => {
    setFiles((prev) => ({ ...prev, [filename]: { ...prev[filename], loading: true, error: null } }));
    try {
      const content = await loadFile(filename);
      setFiles((prev) => ({ ...prev, [filename]: { content, loading: false, saving: false, error: null } }));
    } catch (err) {
      setFiles((prev) => ({ ...prev, [filename]: { ...prev[filename], loading: false, error: String(err) } }));
    }
  }, []);

  useEffect(() => {
    if (!files[activeFile]) {
      fetchFile(activeFile);
    }
  }, [activeFile, files, fetchFile]);

  const handleSave = useCallback(async () => {
    setFiles((prev) => ({ ...prev, [activeFile]: { ...prev[activeFile], saving: true } }));
    try {
      await saveFile(activeFile, current.content);
      setFiles((prev) => ({ ...prev, [activeFile]: { ...prev[activeFile], saving: false, error: null } }));
    } catch (err) {
      setFiles((prev) => ({ ...prev, [activeFile]: { ...prev[activeFile], saving: false, error: String(err) } }));
    }
  }, [activeFile, current.content]);

  const handleReload = useCallback(() => {
    fetchFile(activeFile);
  }, [activeFile, fetchFile]);

  return (
    <div className="flex flex-col h-full">
      {/* Philosophy notice */}
      <div className="px-3 py-2 border-b border-border bg-surface-alt/50">
        <p className="text-[10px] text-fg-muted leading-relaxed">
          Your Personal Agent maintains these files autonomously through daily interaction.
          The agent learns about you and itself, updating identity, persona, and preferences over time.
          You can view or override anything here at any time.
        </p>
      </div>

      {/* Sub-tabs */}
      <div className="flex border-b border-border shrink-0">
        {FILES.map((f) => (
          <button
            key={f.name}
            type="button"
            onClick={() => setActiveFile(f.name)}
            className={cn(
              'px-3 py-1.5 text-[11px] border-b-2 -mb-px transition-colors',
              activeFile === f.name
                ? 'border-accent text-fg'
                : 'border-transparent text-fg-muted hover:text-fg-secondary'
            )}
            title={f.desc}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-border shrink-0">
        <span className="text-[10px] text-fg-muted">
          {FILES.find((f) => f.name === activeFile)?.desc}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handleReload}
            disabled={current.loading}
            className="p-1 rounded text-fg-muted hover:text-fg hover:bg-surface-hover transition-colors"
            title="Reload"
          >
            <RefreshCw className={cn('w-3 h-3', current.loading && 'animate-spin')} />
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={current.loading || current.saving}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20 transition-colors"
            title="Save (Ctrl+S)"
          >
            {current.saving ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Save className="w-3 h-3" />
            )}
            Save
          </button>
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 min-h-0">
        {current.error && (
          <div className="p-2 text-[11px] text-danger bg-danger/5 border-b border-border">
            {current.error}
          </div>
        )}
        {current.loading ? (
          <div className="flex items-center justify-center h-full text-xs text-fg-muted">
            <Loader2 className="w-4 h-4 animate-spin mr-2" />
            Loading...
          </div>
        ) : (
          <textarea
            value={current.content}
            onChange={(e) =>
              setFiles((prev) => ({
                ...prev,
                [activeFile]: { ...prev[activeFile], content: e.target.value },
              }))
            }
            className="w-full h-full bg-transparent text-fg text-xs font-mono p-3 resize-none outline-none border-none"
            spellCheck={false}
            onKeyDown={(e) => {
              if (e.ctrlKey && e.key === 's') {
                e.preventDefault();
                handleSave();
              }
            }}
          />
        )}
      </div>
    </div>
  );
};
