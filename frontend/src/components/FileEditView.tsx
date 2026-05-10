import React, { useState } from 'react';
import { ChevronDown, ChevronRight, FilePenLine } from 'lucide-react';
import { FileEdit } from '../types';

interface FileEditViewProps {
  edit: FileEdit;
  compact?: boolean;
}

function basename(path: string): string {
  return path.replace(/\\/g, '/').split('/').pop() || path;
}

export const FileEditView: React.FC<FileEditViewProps> = ({ edit, compact = false }) => {
  const [expanded, setExpanded] = useState(!compact);
  const added = edit.stats?.added || 0;
  const removed = edit.stats?.removed || 0;

  return (
    <div className="my-[var(--chat-space-sm)] rounded-md border border-border bg-surface/40 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-sm hover:bg-surface-hover transition-colors"
      >
        {expanded ? <ChevronDown className="w-3 h-3 text-fg-muted shrink-0" /> : <ChevronRight className="w-3 h-3 text-fg-muted shrink-0" />}
        <FilePenLine className="w-3 h-3 text-blue-400 shrink-0" />
        <span className="text-fg-secondary truncate flex-1 text-left">Edit {basename(edit.path)}</span>
        <span className="text-green-400 tabular-nums">+{added}</span>
        <span className="text-red-400 tabular-nums">-{removed}</span>
      </button>
      {expanded && (
        <div className="border-t border-border-subtle bg-surface-alt/60">
          <div className="px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-xs text-fg-muted truncate">{edit.path}</div>
          <pre className="max-h-72 overflow-auto px-[var(--chat-bubble-px)] pb-[var(--chat-space-lg)] chat-text-xs font-mono whitespace-pre-wrap text-fg-secondary" style={{lineHeight:'var(--chat-line-height)'}}>
            {edit.unified_diff || '(no textual diff)'}
          </pre>
        </div>
      )}
    </div>
  );
};
