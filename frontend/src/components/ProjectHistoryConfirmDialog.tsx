import React, { useEffect } from 'react';
import { Archive, X } from 'lucide-react';
import type { SessionHistoryProject } from '../types';
import { cn } from './ui/cn';

type ConfirmAction = 'archive' | 'remove';

interface ProjectHistoryConfirmDialogProps {
  isOpen: boolean;
  action: ConfirmAction;
  project: SessionHistoryProject | null;
  loading?: boolean;
  error?: string;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
}

export const ProjectHistoryConfirmDialog: React.FC<ProjectHistoryConfirmDialogProps> = ({
  isOpen,
  action,
  project,
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

  if (!isOpen || !project) return null;

  const isRemove = action === 'remove';
  const title = isRemove ? '移除项目' : '归档项目';
  const confirmLabel = loading ? (isRemove ? '移除中...' : '归档中...') : (isRemove ? '移除' : '归档');
  const description = isRemove
    ? `从历史中移除 ${project.name}。该项目下的对话会被归档，项目文件不会被删除。`
    : `将 ${project.name} 下的对话移入归档，并从项目列表隐藏。项目文件不会被删除。重新打开该文件夹可恢复显示。`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4 backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="project-history-confirm-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !loading) onClose();
      }}
    >
      <div className="w-[520px] max-w-[92vw] rounded-2xl border border-border bg-surface px-6 py-6 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 gap-3">
            <div
              className={cn(
                'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border',
                isRemove
                  ? 'border-danger/25 bg-danger/10 text-danger'
                  : 'border-accent/25 bg-accent/10 text-accent',
              )}
            >
              {isRemove ? <X className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
            </div>
            <div className="min-w-0">
              <h2 id="project-history-confirm-title" className="text-xl font-semibold tracking-normal text-fg">
                {title}
              </h2>
              <p className="mt-2 text-sm leading-6 text-fg-muted">{description}</p>
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

        {project.path && (
          <div className="mt-5 truncate rounded-lg border border-border bg-surface-alt px-3 py-2 text-[11px] text-fg-muted" title={project.path}>
            {project.path}
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
              isRemove
                ? 'bg-danger text-fg-on-danger hover:bg-danger/85'
                : 'bg-accent/85 text-fg-on-accent hover:bg-accent',
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};
