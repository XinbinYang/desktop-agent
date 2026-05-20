import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Wrench, Loader2, Bot } from 'lucide-react';
import { WorkerEvent } from '../types';
import { resolveToolCallLocalPath } from '../lib/localPaths';
import { RevealPathButton } from './RevealPathAction';

interface ToolCallViewProps {
  name: string;
  args: Record<string, any>;
  result?: string;
  status: 'running' | 'success' | 'error';
  durationMs?: number;
  workerEvents?: WorkerEvent[];
  variant?: 'full' | 'event-row' | 'disclosure';
  projectPath?: string | null;
}

/** Shell/bash-style tools get a compact IN/OUT terminal view. */
function isShellTool(name: string): boolean {
  const n = (name || '').toLowerCase();
  return n.includes('shell') || n.includes('bash') || n === 'run_command' || n.includes('terminal');
}

/** Best-effort extraction of the command string from shell tool args. */
function shellCommand(args: Record<string, any>): string {
  if (!args || typeof args !== 'object') return '';
  const raw =
    args.command ?? args.cmd ?? args.script ?? args.shell ?? args.input ?? '';
  if (Array.isArray(raw)) return raw.join(' ');
  return typeof raw === 'string' ? raw : '';
}

function truncateText(value: string, maxChars = 1200, maxLines = 8): string {
  const lines = value.split(/\r?\n/);
  const clippedLines = lines.length > maxLines;
  let next = lines.slice(0, maxLines).join('\n');
  const clippedChars = next.length > maxChars;
  if (clippedChars) next = next.slice(0, maxChars);
  return clippedLines || clippedChars ? `${next}\n...` : next;
}

function firstStringArg(args: Record<string, any>, keys: string[]): string {
  for (const key of keys) {
    const value = args?.[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}

function toolDisplayName(name: string, args: Record<string, any>): string {
  const n = (name || '').toLowerCase();
  if (n.includes('dispatch') || n.includes('worker') || n.includes('agent')) return 'Agent';
  if (isShellTool(name)) return 'Bash';
  if (n.includes('read')) return 'Read';
  if (n.includes('search') || n.includes('grep')) return 'Search';
  if (n.includes('list') || n.includes('ls')) return 'List';
  if (n.includes('write') || n.includes('edit') || n.includes('patch')) return 'Edit';
  if (n.includes('browser')) return 'Browser';
  if (n.includes('web')) return 'Web';
  return name || firstStringArg(args, ['tool', 'name']) || 'Tool';
}

function toolTarget(name: string, args: Record<string, any>): string {
  const n = (name || '').toLowerCase();
  if (n.includes('dispatch') || n.includes('worker') || n.includes('agent')) {
    const tasks = Array.isArray(args?.tasks) ? args.tasks.length : 0;
    if (tasks > 0) return `${tasks} agent${tasks > 1 ? 's' : ''}`;
    return firstStringArg(args, ['task', 'goal', 'prompt']);
  }
  if (isShellTool(name)) return shellCommand(args);
  const direct = firstStringArg(args, ['path', 'file', 'file_path', 'query', 'url', 'command']);
  if (direct) return direct;
  const first = Object.values(args || {}).find((value) => typeof value === 'string' && value.trim());
  return typeof first === 'string' ? first : '';
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

function workerStatus(events: WorkerEvent[]): WorkerEvent['status'] {
  const start = events.find((event) => event.type === 'worker_start');
  const done = events.find((event) => event.type === 'worker_done');
  return done?.status || start?.status || 'running';
}

function workerTitle(workerId: string, events: WorkerEvent[]): string {
  const start = events.find((event) => event.type === 'worker_start');
  const done = events.find((event) => event.type === 'worker_done');
  return start?.task || done?.task || workerId;
}

function workerInput(events: WorkerEvent[]): string {
  const start = events.find((event) => event.type === 'worker_start');
  return start?.task || '';
}

function workerOutput(events: WorkerEvent[]): string {
  const done = [...events].reverse().find((event) => event.type === 'worker_done');
  if (done?.result) return done.result;
  const content = [...events].reverse().find((event) => event.type === 'worker_content' && event.text);
  return content?.text || '';
}

const InlineWorkerTrace: React.FC<{ workerId: string; events: WorkerEvent[] }> = ({ workerId, events }) => {
  const status = workerStatus(events);
  const title = workerTitle(workerId, events);
  const input = workerInput(events);
  const output = workerOutput(events);
  const done = events.find((event) => event.type === 'worker_done');
  const failed = status === 'failed' || status === 'cancelled';

  return (
    <div className="space-y-[var(--chat-space-xs)]">
      <div className="flex items-center gap-2 chat-text-sm">
        {status === 'running' ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-info shrink-0" />
        ) : failed ? (
          <XCircle className="w-3.5 h-3.5 text-danger shrink-0" />
        ) : (
          <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />
        )}
        <span className="font-semibold text-fg">Agent:</span>
        <span className="min-w-0 truncate text-fg-secondary" title={title}>{title}</span>
        {done?.durationMs != null && <span className="ml-auto shrink-0 chat-text-xs text-fg-muted tabular-nums">{done.durationMs}ms</span>}
      </div>
      {(input || output) && (
        <div className="ml-5 rounded-md border border-border-subtle bg-surface-alt/55 px-3 py-2 chat-text-sm text-fg-secondary">
          {input && (
            <div className="flex gap-3">
              <span className="shrink-0 chat-text-xs font-medium uppercase text-fg-muted">IN</span>
              <div className="min-w-0 whitespace-pre-wrap">{truncateText(input, 900, 6)}</div>
            </div>
          )}
          {output && (
            <div className={`${input ? 'mt-2 border-t border-border-subtle pt-2' : ''} flex gap-3`}>
              <span className="shrink-0 chat-text-xs font-medium uppercase text-fg-muted">OUT</span>
              <div className={`min-w-0 whitespace-pre-wrap ${failed ? 'text-danger' : 'text-fg-secondary'}`}>
                {truncateText(output, 1200, 8)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const CompactToolDetails: React.FC<{
  name: string;
  args: Record<string, any>;
  result?: string;
  status: 'running' | 'success' | 'error';
  workerGroups: Record<string, WorkerEvent[]>;
}> = ({ name, args, result, status, workerGroups }) => {
  const isShell = isShellTool(name);
  const command = isShell ? shellCommand(args) : '';
  const hasArgs = Object.keys(args || {}).length > 0;
  const workerEntries = Object.entries(workerGroups);

  return (
    <div className="border-t border-border-subtle px-[var(--chat-bubble-px)] py-[var(--chat-space-sm)] space-y-[var(--chat-space-sm)] chat-text-xs">
      {workerEntries.length > 0 ? (
        <div className="space-y-[var(--chat-space-md)]">
          {workerEntries.map(([workerId, events]) => (
            <InlineWorkerTrace key={workerId} workerId={workerId} events={events} />
          ))}
        </div>
      ) : isShell ? (
        command && (
          <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-surface-alt px-3 py-2 font-mono text-fg-secondary">
            {truncateText(command)}
          </pre>
        )
      ) : hasArgs ? (
        <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-surface-alt px-3 py-2 font-mono text-fg-secondary">
          {truncateText(JSON.stringify(args, null, 2))}
        </pre>
      ) : null}
      {workerEntries.length === 0 && result != null && (
        <pre className={`max-h-40 overflow-auto whitespace-pre-wrap rounded bg-surface-alt px-3 py-2 font-mono ${status === 'error' ? 'text-danger' : 'text-fg-secondary'}`}>
          {truncateText(result)}
        </pre>
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
  variant = 'full',
  projectPath,
}) => {
  const workerGroups = groupWorkerEvents(workerEvents);
  const workerCount = Object.keys(workerGroups).length;
  const [expanded, setExpanded] = useState(workerCount > 0 && variant !== 'full');
  const isShell = isShellTool(name);
  const command = isShell ? shellCommand(args) : '';
  const canExpand = status !== 'running' || workerCount > 0 || result != null;
  const revealPath = resolveToolCallLocalPath(name, args, result, { projectPath });

  useEffect(() => {
    if (variant !== 'full' && workerCount > 0) {
      setExpanded(true);
    }
  }, [variant, workerCount]);

  if (variant === 'event-row' || variant === 'disclosure') {
    const label = toolDisplayName(name, args);
    const target = toolTarget(name, args);
    const disclosure = variant === 'disclosure';

    return (
      <div
        className={`my-[var(--chat-space-xs)] rounded-md border overflow-hidden ${
          disclosure
            ? 'border-border-subtle bg-surface/40'
            : status === 'error'
              ? 'border-danger/30 bg-danger/5'
              : 'border-border-subtle bg-surface/45'
        }`}
        data-testid={disclosure ? 'tool-disclosure' : 'tool-event-row'}
      >
        <div className="w-full flex min-w-0 items-center hover:bg-surface-hover transition-colors">
          <button
            type="button"
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse tool call details' : 'Expand tool call details'}
            onClick={() => canExpand && setExpanded((v) => !v)}
            className="flex min-w-0 flex-1 items-center gap-2 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-xs text-left"
          >
            {status === 'running' ? (
              <Loader2 className="w-3.5 h-3.5 text-info animate-spin shrink-0" />
            ) : status === 'error' ? (
              <XCircle className="w-3.5 h-3.5 text-danger shrink-0" />
            ) : (
              <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />
            )}
            {workerCount > 0 ? (
              <Bot className="w-3.5 h-3.5 text-fg-muted shrink-0" />
            ) : (
              <Wrench className="w-3.5 h-3.5 text-fg-muted shrink-0" />
            )}
            <span className="font-medium text-fg-secondary shrink-0">
              {disclosure ? `Used ${label}` : label}
            </span>
            {target && (
              <span
                className={`min-w-0 flex-1 truncate text-fg-muted ${workerCount > 0 ? '' : 'font-mono'}`}
                title={target}
              >
                {target}
              </span>
            )}
            {typeof durationMs === 'number' && (
              <span className="text-fg-muted tabular-nums shrink-0">{durationMs}ms</span>
            )}
            {canExpand ? (
              expanded ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-fg-muted shrink-0" />
            ) : (
              <span className="text-info/80 shrink-0 font-medium">Running</span>
            )}
          </button>
          <RevealPathButton
            path={revealPath}
            projectPath={projectPath}
            className="mr-2 h-6 w-6"
            ariaLabel={revealPath ? `Show in folder: ${revealPath}` : undefined}
          />
        </div>
        {expanded && canExpand && (
          <CompactToolDetails
            name={name}
            args={args}
            result={result}
            status={status}
            workerGroups={workerGroups}
          />
        )}
      </div>
    );
  }

  return (
    <div className="my-[var(--chat-space-sm)] rounded-md border border-border bg-surface/40 overflow-hidden">
      <div className="w-full flex min-w-0 items-center hover:bg-surface-hover transition-colors">
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={expanded ? 'Collapse tool call details' : 'Expand tool call details'}
          onClick={() => (status !== 'running' || workerCount > 0) && setExpanded(!expanded)}
          className="flex min-w-0 flex-1 items-center gap-2 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-sm"
        >
          {status === 'running' ? (
            <Loader2 className="w-3.5 h-3.5 text-info animate-spin shrink-0" />
          ) : status === 'error' ? (
            <XCircle className="w-3.5 h-3.5 text-danger shrink-0" />
          ) : (
            <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />
          )}
          <Wrench className="w-3.5 h-3.5 text-fg-muted shrink-0" />
          {isShell ? (
            <span className="flex items-baseline gap-1.5 truncate flex-1 text-left">
              <span className="text-fg-secondary font-medium shrink-0">Bash</span>
              {command && (
                <span className="text-fg-muted font-mono chat-text-xs truncate">{command}</span>
              )}
            </span>
          ) : (
            <span className="text-fg-secondary truncate flex-1 text-left">{name}</span>
          )}
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
        <RevealPathButton
          path={revealPath}
          projectPath={projectPath}
          className="mr-2 h-7 w-7"
          ariaLabel={revealPath ? `Show in folder: ${revealPath}` : undefined}
        />
      </div>
      {expanded && (status !== 'running' || workerCount > 0) && (
        <div className="px-[var(--chat-bubble-px)] pb-[var(--chat-space-lg)] space-y-[var(--chat-space-md)] chat-text-sm font-mono border-t border-border-subtle pt-[var(--chat-space-md)]">
          {isShell ? (
            <>
              <div className="bg-surface-alt rounded-md overflow-hidden border-l-2 border-l-info/70">
                <div className="px-[var(--chat-space-lg)] pt-[var(--chat-space-xs)] chat-text-xs text-fg-muted select-none">IN</div>
                <div className="px-[var(--chat-space-lg)] pb-[var(--chat-space-md)] pt-[var(--chat-space-xs)] whitespace-pre-wrap text-fg-secondary overflow-x-auto" style={{ lineHeight: 'var(--chat-line-height)' }}>
                  {command || JSON.stringify(args)}
                </div>
              </div>
              {result != null && (
                <div className={`bg-surface-alt rounded-md overflow-hidden border-l-2 ${status === 'error' ? 'border-l-danger/70' : 'border-l-success/60'}`}>
                  <div className="px-[var(--chat-space-lg)] pt-[var(--chat-space-xs)] chat-text-xs text-fg-muted select-none">OUT</div>
                  <div className={`px-[var(--chat-space-lg)] pb-[var(--chat-space-md)] pt-[var(--chat-space-xs)] whitespace-pre-wrap max-h-80 overflow-auto ${status === 'error' ? 'text-danger' : 'text-fg-secondary'}`} style={{ lineHeight: 'var(--chat-line-height)' }}>
                    {result}
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <div className="text-fg-muted bg-surface-alt rounded-md px-[var(--chat-space-lg)] py-[var(--chat-space-md)] overflow-x-auto">
                {JSON.stringify(args, null, 2)}
              </div>
              {result != null && (
                <div className={`bg-surface-alt rounded-md px-[var(--chat-space-lg)] py-[var(--chat-space-md)] whitespace-pre-wrap max-h-80 overflow-auto ${status === 'error' ? 'text-danger' : 'text-fg-secondary'}`} style={{lineHeight:'var(--chat-line-height)'}}>
                  {result}
                </div>
              )}
            </>
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
