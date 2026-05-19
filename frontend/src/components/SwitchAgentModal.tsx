import React from 'react';
import { X, ArrowRight } from 'lucide-react';
import type { AgentType } from '../types';

interface SwitchAgentModalProps {
  isOpen: boolean;
  from: AgentType;
  to: AgentType;
  reason: string;
  onSwitch: () => void;
  onDismiss: () => void;
  onNeverAsk: () => void;
}

export const SwitchAgentModal: React.FC<SwitchAgentModalProps> = ({
  isOpen,
  from,
  to,
  reason,
  onSwitch,
  onDismiss,
  onNeverAsk,
}) => {
  if (!isOpen) return null;

  const agentName = (type: AgentType) =>
    type === 'personal' ? 'Personal Agent' : 'Coding Agent';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-surface border border-border rounded-lg shadow-xl w-full max-w-sm mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <span className="text-sm font-medium">Switch Agent?</span>
          <button
            type="button"
            onClick={onDismiss}
            className="text-fg-muted hover:text-fg p-1 rounded hover:bg-surface-hover"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-4 space-y-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-fg-muted">{agentName(from)}</span>
            <ArrowRight className="w-4 h-4 text-accent" />
            <span className="text-fg font-medium">{agentName(to)}</span>
          </div>
          <p className="text-xs text-fg-muted">{reason}</p>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-surface-alt/50">
          <button
            type="button"
            onClick={onNeverAsk}
            className="text-[10px] text-fg-muted hover:text-fg-secondary transition-colors"
          >
            Don't ask again
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onDismiss}
              className="px-3 py-1.5 text-xs rounded text-fg-secondary hover:bg-surface-hover transition-colors"
            >
              Stay
            </button>
            <button
              type="button"
              onClick={onSwitch}
              className="px-3 py-1.5 text-xs rounded bg-accent text-fg-on-accent hover:bg-accent/90 transition-colors font-medium"
            >
              Switch to {agentName(to)}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
