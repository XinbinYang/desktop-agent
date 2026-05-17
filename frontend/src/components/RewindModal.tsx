import React, { useEffect } from 'react';
import { AlertTriangle, RotateCcw, X } from 'lucide-react';
import type { ConversationCheckpoint } from '../types';

interface RewindModalProps {
  open: boolean;
  checkpoints: ConversationCheckpoint[];
  onClose: () => void;
  onLoad: () => Promise<ConversationCheckpoint[]>;
  onRewind: (checkpointId: string) => void;
  isRunning?: boolean;
}

function formatTime(seconds?: number): string {
  if (!seconds) return '';
  const ms = seconds > 10_000_000_000 ? seconds : seconds * 1000;
  return new Date(ms).toLocaleString();
}

export const RewindModal: React.FC<RewindModalProps> = ({
  open,
  checkpoints,
  onClose,
  onLoad,
  onRewind,
  isRunning,
}) => {
  useEffect(() => {
    if (open) void onLoad();
  }, [open, onLoad]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/45 p-4">
      <div className="w-full max-w-xl rounded-lg border border-border bg-surface shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <RotateCcw className="w-4 h-4 text-accent" />
            <div className="text-sm font-semibold text-fg">Rewind</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-fg-muted hover:text-fg hover:bg-surface-hover"
            aria-label="Close rewind"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 py-3">
          <div className="mb-3 flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>Conversation rewind only. File system and worktree changes are not reverted in v1.</span>
          </div>

          <div className="max-h-[52vh] overflow-y-auto space-y-1">
            {checkpoints.length === 0 ? (
              <div className="py-8 text-center text-sm text-fg-muted">No checkpoints yet.</div>
            ) : (
              checkpoints.map((checkpoint) => (
                <button
                  key={checkpoint.id}
                  type="button"
                  disabled={isRunning}
                  onClick={() => {
                    onRewind(checkpoint.id);
                    onClose();
                  }}
                  className="w-full rounded-md border border-border-subtle bg-surface-alt px-3 py-2 text-left hover:bg-surface-hover disabled:opacity-50 transition-colors"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[11px] font-mono text-accent">#{checkpoint.index}</span>
                    <span className="text-[11px] text-fg-muted">{formatTime(checkpoint.created_at)}</span>
                  </div>
                  <div className="mt-1 text-sm text-fg line-clamp-2">{checkpoint.preview}</div>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
