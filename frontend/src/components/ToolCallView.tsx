import React, { useState } from 'react';
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Wrench, Loader2, Bot } from 'lucide-react';
import { WorkerEvent } from '../types';

interface ToolCallViewProps {
  name: string;
  args: Record<string, any>;
  result?: string;
  status: 'running' | 'success' | 'error';
  durationMs?: number;
  workerEvents?: WorkerEvent[];
}

function groupWorkerEvents(events: WorkerEvent[] = []): Record<string, WorkerEvent[]> {
  return events.reduce<Record<string, WorkerEvent[]>>((acc, event) => {
    const id = event.workerId || 'worker';
    acc[id] = [...(acc[id] || []), event];
    return acc;
  }, {});
}

const WorkerCard: React.FC<{ workerId: string; events: WorkerEvent[] }> = ({ workerId, events }) => {
  const [expanded, setExpanded] = useState(false);
  const start = events.find((event) => event.type === 'worker_start');
  const done = events.find((event) => event.type === 'worker_done');
  const toolEvents = events.filter((event) => event.type === 'worker_tool_call');
  const contentEvents = events.filter((event) => event.type === 'worker_content');
  const status = done?.status || start?.status || 'running';

  return (
    <div className="rounded-md border border-border-subtle bg-surface/60 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-xs hover:bg-surface-hover transition-colors"
      >
        {status === 'running' ? (
          <Loader2 className="w-3 h-3 text-info animate-spin shrink-0" />
        ) : status === 'failed' || status === 'cancelled' ? (
          <XCircle className="w-3 h-3 text-danger shrink-0" />
        ) : (
          <CheckCircle2 className="w-3 h-3 text-success shrink-0" />
        )}
        <Bot className="w-3 h-3 text-fg-muted shrink-0" />
        <span className="text-fg-secondary truncate flex-1 text-left">
          Agent: {start?.task || workerId}
        </span>
        {done?.durationMs != null && <span className="text-fg-muted tabular-nums">{done.durationMs}ms</span>}
        {expanded ? <ChevronDown className="w-3 h-3 text-fg-muted shrink-0" /> : <ChevronRight className="w-3 h-3 text-fg-muted shrink-0" />}
      </button>
      {expanded && (
        <div className="px-[var(--chat-bubble-px)] pb-[var(--chat-space-md)] space-y-[var(--chat-space-md)] chat-text-xs border-t border-border-subtle pt-[var(--chat-space-md)]">
          <div className="text-fg-muted">
            {workerId}
            {start?.profile ? ` · ${start.profile}` : ''}
            {done?.iterations != null ? ` · ${done.iterations} iterations` : ''}
          </div>
          {toolEvents.length > 0 && (
            <div className="space-y-[var(--chat-space-xs)]">
              {toolEvents.map((event, index) => (
                <div key={`${event.toolName}-${index}`} className="rounded bg-surface-alt px-[var(--chat-space-md)] py-[var(--chat-space-xs)] font-mono text-fg-secondary">
                  <span className="text-info">{event.toolName}</span>
                  {event.toolDurationMs != null && <span className="text-fg-muted"> {event.toolDurationMs}ms</span>}
                  {event.toolResult && <div className="mt-[var(--chat-space-xs)] whitespace-pre-wrap">{event.toolResult}</div>}
                </div>
              ))}
            </div>
          )}
          {contentEvents.map((event, index) => (
            <div key={`content-${index}`} className="rounded bg-surface-alt px-[var(--chat-space-md)] py-[var(--chat-space-xs)] text-fg-secondary whitespace-pre-wrap">
              {event.text}
            </div>
          ))}
          {done?.result && (
            <div className="rounded bg-surface-alt px-[var(--chat-space-md)] py-[var(--chat-space-xs)] text-fg-secondary whitespace-pre-wrap">
              {done.result}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export const ToolCallView: React.FC<ToolCallViewProps> = ({
  name,
  args,
  result,
  status,
  durationMs,
  workerEvents,
}) => {
  const [expanded, setExpanded] = useState(false);
  const workerGroups = groupWorkerEvents(workerEvents);
  const workerCount = Object.keys(workerGroups).length;

  return (
    <div className="my-[var(--chat-space-sm)] rounded-md border border-border bg-surface/40 overflow-hidden">
      <button
        type="button"
        aria-expanded={expanded}
        aria-label={expanded ? 'Collapse tool call details' : 'Expand tool call details'}
        onClick={() => (status !== 'running' || workerCount > 0) && setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-sm hover:bg-surface-hover transition-colors"
      >
        {status === 'running' ? (
          <Loader2 className="w-3.5 h-3.5 text-info animate-spin shrink-0" />
        ) : status === 'error' ? (
          <XCircle className="w-3.5 h-3.5 text-danger shrink-0" />
        ) : (
          <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />
        )}
        <Wrench className="w-3.5 h-3.5 text-fg-muted shrink-0" />
        <span className="text-fg-secondary truncate flex-1 text-left">{name}</span>
        {typeof durationMs === 'number' && (
          <span className="text-fg-muted tabular-nums">{durationMs}ms</span>
        )}
        {workerCount > 0 && (
          <span className="chat-text-xs text-info/90 shrink-0">{workerCount} agent{workerCount > 1 ? 's' : ''}</span>
        )}
        {status === 'running' ? (
          <span className="chat-text-xs text-info/80 shrink-0 font-medium">Running</span>
        ) : expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-fg-muted shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-fg-muted shrink-0" />
        )}
      </button>
      {expanded && (status !== 'running' || workerCount > 0) && (
        <div className="px-[var(--chat-bubble-px)] pb-[var(--chat-space-lg)] space-y-[var(--chat-space-md)] chat-text-sm font-mono border-t border-border-subtle pt-[var(--chat-space-md)]">
          <div className="text-fg-muted bg-surface-alt rounded-md px-[var(--chat-space-lg)] py-[var(--chat-space-md)] overflow-x-auto">
            {JSON.stringify(args, null, 2)}
          </div>
          {result != null && (
            <div className={`bg-surface-alt rounded-md px-[var(--chat-space-lg)] py-[var(--chat-space-md)] whitespace-pre-wrap max-h-80 overflow-auto ${status === 'error' ? 'text-danger' : 'text-fg-secondary'}`} style={{lineHeight:'var(--chat-line-height)'}}>
              {result}
            </div>
          )}
          {workerCount > 0 && (
            <div className="space-y-[var(--chat-space-md)]">
              {Object.entries(workerGroups).map(([workerId, events]) => (
                <WorkerCard key={workerId} workerId={workerId} events={events} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
