import React, { useEffect } from 'react';
import { MessageSquare, Trash2, X } from 'lucide-react';
import type { SessionHistoryItem } from '../types';
import { cn } from './ui/cn';

interface SessionDeleteConfirmDialogProps {
  isOpen: boolean;
  session: SessionHistoryItem | null;
  loading?: boolean;
  error?: string;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
}

function sessionLabel(session: SessionHistoryItem): string {
  const title = (session.title || '').trim();
  if (title) return title;
  return session.id
    .replace(/^session_personal_/, '')
    .replace(/^session_coding_/, '')
    .replace(/^session_/, '#');
}

export const SessionDeleteConfirmDialog: React.FC<SessionDeleteConfirmDialogProps> = ({
  isOpen,
  session,
  loading = false,
  error = '',
  onClose,
  onConfirm,
}) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !loading) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, loading, onClose]);

  if (!isOpen || !session) return null;

  const label = sessionLabel(session);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-session-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !loading) onClose();
      }}
    >
      <div className="w-[520px] max-w-[92vw] rounded-2xl border border-border bg-surface px-6 py-6 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 gap-3">
            <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-danger/25 bg-danger/10 text-danger">
              <Trash2 className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <h2 id="delete-session-title" className="text-xl font-semibold tracking-normal text-fg">
                删除会话
              </h2>
              <p className="mt-2 text-sm leading-6 text-fg-muted">
                永久删除本地会话记录，不能从归档恢复。项目文件不会被删除。
              </p>
            </div>
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

        <div className="mt-5 flex min-w-0 items-center gap-2 rounded-lg border border-border bg-surface-alt px-3 py-2 text-xs text-fg-secondary">
          <MessageSquare className="h-3.5 w-3.5 shrink-0 text-fg-muted" />
          <span className="truncate" title={label}>{label}</span>
        </div>

        {session.project_path && (
          <div className="mt-2 truncate text-[11px] text-fg-muted" title={session.project_path}>
            {session.project_path}
          </div>
        )}

        {error && (
          <div className="mt-3 rounded-md bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}

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
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className={cn(
              'min-w-20 rounded-xl px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
              'bg-danger text-fg-on-danger hover:bg-danger/85',
            )}
          >
            {loading ? '删除中...' : '删除'}
          </button>
        </div>
      </div>
    </div>
  );
};
