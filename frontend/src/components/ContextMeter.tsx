import React from 'react';
import { Gauge } from 'lucide-react';
import type { ContextUsage } from '../types';

interface ContextMeterProps {
  usage?: ContextUsage | null;
  onCompact?: () => void;
  disabled?: boolean;
}

function formatTokens(value?: number): string {
  const n = Number(value || 0);
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(Math.max(0, Math.round(n)));
}

export const ContextMeter: React.FC<ContextMeterProps> = ({ usage, onCompact, disabled }) => {
  const percent = Math.max(0, Math.min(100, Number(usage?.used_percent || 0)));
  const status = usage?.status || 'ok';
  const tone =
    status === 'critical'
      ? 'text-danger border-danger/40 bg-danger/10'
      : status === 'warning'
        ? 'text-warning border-warning/40 bg-warning/10'
        : 'text-success border-success/30 bg-success/10';
  const transcriptNote = usage?.context_truncated
    ? `, provider window ${usage.context_message_count ?? '?'} of ${usage.transcript_message_count ?? '?'} messages`
    : '';
  const title = usage
    ? `Context ${percent.toFixed(1)}% (${formatTokens(usage.used_tokens)} / ${formatTokens(usage.model_context)} tokens, ${usage.source}${transcriptNote})`
    : 'Context usage loading';

  return (
    <button
      type="button"
      onClick={onCompact}
      disabled={disabled}
      title={`${title}. Click to compact.`}
      className={`h-7 shrink-0 inline-flex items-center gap-1.5 rounded-md border px-2 text-[11px] font-medium transition-colors disabled:opacity-50 ${tone}`}
    >
      <Gauge className="w-3.5 h-3.5" />
      <span className="tabular-nums">{percent.toFixed(0)}%</span>
      {usage?.context_truncated && <span className="text-current/75">trimmed</span>}
      <span className="hidden sm:inline text-current/75">{formatTokens(usage?.used_tokens)} / {formatTokens(usage?.model_context)}</span>
    </button>
  );
};
