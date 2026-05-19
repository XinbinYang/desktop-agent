import React, { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';

interface ProjectRenameDialogProps {
  isOpen: boolean;
  initialName: string;
  projectPath?: string;
  loading?: boolean;
  error?: string;
  onClose: () => void;
  onSubmit: (name: string) => void | Promise<void>;
}

export const ProjectRenameDialog: React.FC<ProjectRenameDialogProps> = ({
  isOpen,
  initialName,
  projectPath,
  loading = false,
  error = '',
  onClose,
  onSubmit,
}) => {
  const [name, setName] = useState(initialName);
  const [localError, setLocalError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    setName(initialName);
    setLocalError('');
    window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
  }, [initialName, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !loading) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, loading, onClose]);

  if (!isOpen) return null;

  const trimmed = name.trim();
  const hasChanged = trimmed !== initialName.trim();
  const message = localError || error;

  const submit = async (event?: React.FormEvent) => {
    event?.preventDefault();
    if (loading) return;
    if (!trimmed) {
      setLocalError('项目名称不能为空');
      return;
    }
    await onSubmit(trimmed);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rename-project-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !loading) onClose();
      }}
    >
      <form
        onSubmit={submit}
        className="w-[520px] max-w-[92vw] rounded-2xl border border-border bg-surface px-6 py-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 id="rename-project-title" className="text-xl font-semibold tracking-normal text-fg">
              重命名项目
            </h2>
            <p className="mt-2 text-sm text-fg-muted">保持简短且易于识别</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="rounded p-1 text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg disabled:opacity-50"
            aria-label="关闭"
            title="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5">
          <input
            ref={inputRef}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setLocalError('');
            }}
            aria-label="项目名称"
            className="h-12 w-full rounded-xl border border-border bg-surface-input px-4 text-sm text-fg outline-none transition-colors placeholder:text-fg-muted focus:border-accent focus:ring-2 focus:ring-accent/20"
          />
          {projectPath && (
            <div className="mt-2 truncate text-[11px] text-fg-muted" title={projectPath}>
              {projectPath}
            </div>
          )}
          {message && (
            <div className="mt-2 rounded-md bg-danger/10 px-3 py-2 text-xs text-danger">
              {message}
            </div>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="min-w-20 rounded-xl border border-border bg-surface px-4 py-2 text-sm text-fg-secondary transition-colors hover:bg-surface-hover hover:text-fg disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={loading || !trimmed || !hasChanged}
            className="min-w-20 rounded-xl bg-accent/85 px-4 py-2 text-sm font-medium text-fg-on-accent transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? '保存中...' : '保存'}
          </button>
        </div>
      </form>
    </div>
  );
};
