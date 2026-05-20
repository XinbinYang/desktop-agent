import React, { useState, useEffect, useCallback } from 'react';
import { Save, RefreshCw, Loader2 } from 'lucide-react';
import { API_BASE } from '../../config';
import { cn } from '../ui/cn';
import type { AgentProfile } from '../../types';

const FILES = [
  { name: 'SOUL.md', label: 'SOUL', desc: '人格核心' },
  { name: 'INNER.md', label: 'INNER', desc: '内在世界' },
  { name: 'IDENTITY.md', label: 'IDENTITY', desc: '身份信息' },
  { name: 'USER.md', label: 'USER', desc: '用户画像' },
];

interface FileState {
  content: string;
  originalContent: string;
  loading: boolean;
  saving: boolean;
  error: string | null;
}

interface SoulEditorProps {
  profile?: AgentProfile;
  onProfileChanged?: (profile: AgentProfile) => void;
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

export const SoulEditor: React.FC<SoulEditorProps> = ({ profile, onProfileChanged }) => {
  const [profileForm, setProfileForm] = useState({
    display_name: profile?.display_name || 'Personal Agent',
    avatar_emoji: profile?.avatar_emoji || '',
    subtitle: profile?.subtitle || '',
  });
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [activeFile, setActiveFile] = useState('SOUL.md');
  const [files, setFiles] = useState<Record<string, FileState>>({});

  const current = files[activeFile] || { content: '', originalContent: '', loading: true, saving: false, error: null };
  const hasUnsavedChanges = current.content !== current.originalContent;

  useEffect(() => {
    setProfileForm({
      display_name: profile?.display_name || 'Personal Agent',
      avatar_emoji: profile?.avatar_emoji || '',
      subtitle: profile?.subtitle || '',
    });
  }, [profile?.display_name, profile?.avatar_emoji, profile?.subtitle]);

  const handleProfileSave = useCallback(async () => {
    setProfileSaving(true);
    setProfileError(null);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/profile`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profileForm),
      });
      if (!res.ok) throw new Error(`Failed to save: ${res.status}`);
      const data = await res.json();
      if (data.profile) onProfileChanged?.(data.profile as AgentProfile);
    } catch (err) {
      setProfileError(String(err));
    } finally {
      setProfileSaving(false);
    }
  }, [onProfileChanged, profileForm]);

  const fetchFile = useCallback(async (filename: string) => {
    setFiles((prev) => ({
      ...prev,
      [filename]: {
        content: prev[filename]?.content || '',
        originalContent: prev[filename]?.originalContent || '',
        saving: prev[filename]?.saving || false,
        loading: true,
        error: null,
      },
    }));
    try {
      const content = await loadFile(filename);
      setFiles((prev) => ({ ...prev, [filename]: { content, originalContent: content, loading: false, saving: false, error: null } }));
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
    if (!window.confirm('这些身份与偏好文件通常由 Agent 自动维护。确认要保存你的手动修正吗？')) {
      return;
    }
    setFiles((prev) => ({ ...prev, [activeFile]: { ...prev[activeFile], saving: true } }));
    try {
      await saveFile(activeFile, current.content);
      setFiles((prev) => ({ ...prev, [activeFile]: { ...prev[activeFile], originalContent: current.content, saving: false, error: null } }));
    } catch (err) {
      setFiles((prev) => ({ ...prev, [activeFile]: { ...prev[activeFile], saving: false, error: String(err) } }));
    }
  }, [activeFile, current.content]);

  const handleReload = useCallback(() => {
    fetchFile(activeFile);
  }, [activeFile, fetchFile]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-3 border-b border-border bg-surface">
        <div className="flex items-start gap-3">
          <input
            value={profileForm.avatar_emoji}
            onChange={(e) => setProfileForm((prev) => ({ ...prev, avatar_emoji: e.target.value }))}
            className="h-10 w-10 shrink-0 rounded-full border border-border bg-surface-alt text-center text-lg outline-none focus:border-accent/60"
            maxLength={8}
            aria-label="Personal avatar"
            placeholder="*"
          />
          <div className="min-w-0 flex-1 space-y-2">
            <input
              value={profileForm.display_name}
              onChange={(e) => setProfileForm((prev) => ({ ...prev, display_name: e.target.value }))}
              className="w-full rounded border border-border bg-surface-alt px-2 py-1 text-sm font-medium text-fg outline-none focus:border-accent/60"
              maxLength={80}
              aria-label="Personal display name"
              placeholder="Personal Agent"
            />
            <input
              value={profileForm.subtitle}
              onChange={(e) => setProfileForm((prev) => ({ ...prev, subtitle: e.target.value }))}
              className="w-full rounded border border-border bg-surface-alt px-2 py-1 text-[11px] text-fg-secondary outline-none focus:border-accent/60"
              maxLength={160}
              aria-label="Personal subtitle"
              placeholder="A short identity note"
            />
            {profileError && <div className="text-[10px] text-danger">{profileError}</div>}
          </div>
          <button
            type="button"
            onClick={handleProfileSave}
            disabled={profileSaving || !profileForm.display_name.trim()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded bg-accent/10 px-2.5 py-1 text-[11px] font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-50"
          >
            {profileSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
            Save
          </button>
        </div>
      </div>
      {/* Philosophy notice */}
      <div className="px-3 py-2 border-b border-border bg-surface-alt/50">
        <p className="text-[10px] text-fg-muted leading-relaxed">
          身份与偏好由 Agent 自动维护。你可以在这里查看并修正明显不准确的内容，保存会覆盖 Agent 的可变工作区文件。
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
          {hasUnsavedChanges ? ' · 未保存更改' : ''}
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
            title="确认保存手动修正 (Ctrl+S)"
          >
            {current.saving ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Save className="w-3 h-3" />
            )}
            保存修正
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
