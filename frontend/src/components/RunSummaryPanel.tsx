import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, GitBranch, PlayCircle, ShieldCheck, Trash2 } from 'lucide-react';
import type { RunEvent } from '../types';

interface RunSummaryPanelProps {
  events: RunEvent[];
  onOpenWorktree?: (runId: string) => Promise<void> | void;
  onApplyRun?: (runId: string) => Promise<void> | void;
  onMergeRun?: (runId: string) => Promise<void> | void;
  onDiscardRun?: (runId: string) => Promise<void> | void;
}

function eventRunId(event: RunEvent): string {
  return event.runId || event.data?.run_id || 'unknown';
}

function formatTime(ts?: number): string {
  if (!ts) return '';
  return new Date(ts).toLocaleTimeString();
}

function lastEvent(items: RunEvent[]): RunEvent | undefined {
  return items.length ? items[items.length - 1] : undefined;
}

function isCollaborationEvent(event: RunEvent): boolean {
  return event.type.startsWith('collaboration_') ||
    event.type === 'agent_message' ||
    event.type === 'artifact_ready' ||
    event.type === 'decision_required';
}

function statusClass(status?: string): string {
  if (status === 'completed' || status === 'applied' || status === 'merged') return 'text-emerald-400';
  if (status === 'failed' || status === 'cancelled' || status === 'max_iterations_reached') return 'text-red-400';
  return 'text-fg-secondary';
}

function qualitySummary(completed?: RunEvent): { label: string; detail: string; tone: string } {
  if (!completed) {
    return {
      label: 'Agent is working',
      detail: 'The agent is still exploring, editing, or checking the result.',
      tone: 'border-border bg-surface-alt text-fg-secondary',
    };
  }
  const verification = completed.data?.verification_passed;
  const review = completed.data?.review_passed;
  if (verification === true && review !== false) {
    return {
      label: 'Ready for you',
      detail: 'The agent says the change was checked and has no blocking review issue.',
      tone: 'border-emerald-500/35 bg-emerald-500/10 text-emerald-300',
    };
  }
  if (verification === false) {
    return {
      label: 'Needs agent follow-up',
      detail: 'The change is not verified yet. The agent should keep fixing and checking it.',
      tone: 'border-amber-500/35 bg-amber-500/10 text-amber-300',
    };
  }
  if (review === false) {
    return {
      label: 'Needs review fix',
      detail: 'The automated review found a blocking issue that the agent should address.',
      tone: 'border-amber-500/35 bg-amber-500/10 text-amber-300',
    };
  }
  return {
    label: 'Check pending',
    detail: 'The run ended, but there is not enough quality evidence yet.',
    tone: 'border-border bg-surface-alt text-fg-secondary',
  };
}

export function RunSummaryPanel({ events, onOpenWorktree, onApplyRun, onMergeRun, onDiscardRun }: RunSummaryPanelProps) {
  const grouped = useMemo(() => {
    const map = new Map<string, RunEvent[]>();
    for (const event of events) {
      const key = eventRunId(event);
      map.set(key, [...(map.get(key) || []), event]);
    }
    return [...map.entries()]
      .map(([runId, items]) => ({ runId, items }))
      .sort((a, b) => (lastEvent(b.items)?.timestamp || 0) - (lastEvent(a.items)?.timestamp || 0));
  }, [events]);

  const [selectedRunId, setSelectedRunId] = useState<string>('');

  useEffect(() => {
    if (!selectedRunId && grouped[0]) setSelectedRunId(grouped[0].runId);
  }, [grouped, selectedRunId]);

  const selected = grouped.find((g) => g.runId === selectedRunId) || grouped[0];
  const items = selected?.items || [];
  const created = items.find((e) => e.type === 'run_created' || e.type === 'collaboration_run_created');
  const context = [...items].reverse().find((e) => e.type === 'context_pack');
  const completed = [...items].reverse().find((e) => e.type === 'run_completed' || e.type === 'collaboration_run_completed');
  const guardrails = items.filter((e) => e.type === 'guardrail_decision' || e.type === 'approval_required');
  const verifications = items.filter((e) => e.type === 'verification_result');
  const findings = items.filter((e) => e.type === 'review_finding');
  const collaborationEvents = items.filter(isCollaborationEvent);
  const selectedIsCollaboration = collaborationEvents.length > 0;
  const status = completed?.data?.status || created?.data?.status || 'running';
  const quality = qualitySummary(completed);

  if (grouped.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-fg-muted">
        No coding runs yet
      </div>
    );
  }

  return (
    <div className="h-full flex min-w-0 bg-surface">
      <div className="w-56 shrink-0 border-r border-border overflow-y-auto">
        {grouped.map((run) => {
          const runCreated = run.items.find((e) => e.type === 'run_created' || e.type === 'collaboration_run_created');
          const runDone = [...run.items].reverse().find((e) => e.type === 'run_completed' || e.type === 'collaboration_run_completed');
          const runStatus = runDone?.data?.status || 'running';
          const isCollab = run.items.some(isCollaborationEvent);
          return (
            <button
              key={run.runId}
              type="button"
              onClick={() => setSelectedRunId(run.runId)}
              className={`w-full text-left px-3 py-2 border-b border-border/70 hover:bg-surface-hover ${selected?.runId === run.runId ? 'bg-surface-alt' : ''}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-mono text-fg truncate">{run.runId}</span>
                <span className={`text-[10px] uppercase ${statusClass(runStatus)}`}>{runStatus}</span>
              </div>
              <div className="mt-1 text-[11px] text-fg-muted truncate">
                {isCollab ? 'collab' : runCreated?.data?.mode || 'current'} {formatTime(lastEvent(run.items)?.timestamp)}
              </div>
            </button>
          );
        })}
      </div>

      <div className="flex-1 min-w-0 overflow-y-auto p-3 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wider text-fg-muted">Run Summary</div>
            <div className="mt-1 text-sm font-semibold text-fg font-mono truncate">{selected?.runId}</div>
            <div className={`mt-1 text-xs ${statusClass(status)}`}>{status}</div>
          </div>
          {!selectedIsCollaboration && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => selected && onOpenWorktree?.(selected.runId)}
              className="px-2 py-1 text-xs rounded bg-surface-alt hover:bg-surface-hover text-fg border border-border"
              title="Open worktree as the current project"
            >
              Open
            </button>
            <button
              type="button"
              onClick={() => selected && onApplyRun?.(selected.runId)}
              className="px-2 py-1 text-xs rounded bg-surface-alt hover:bg-surface-hover text-fg border border-border"
              title="Apply worktree diff to current project"
            >
              Apply
            </button>
            <button
              type="button"
              onClick={() => selected && onMergeRun?.(selected.runId)}
              className="px-2 py-1 text-xs rounded bg-surface-alt hover:bg-surface-hover text-fg border border-border inline-flex items-center gap-1"
              title="Create and merge a local branch"
            >
              <GitBranch className="w-3 h-3" /> Merge
            </button>
            <button
              type="button"
              onClick={() => selected && onDiscardRun?.(selected.runId)}
              className="px-2 py-1 text-xs rounded bg-surface-alt hover:bg-red-500/20 text-fg border border-border inline-flex items-center gap-1"
              title="Discard worktree"
            >
              <Trash2 className="w-3 h-3" /> Discard
            </button>
          </div>
          )}
        </div>

        {created && (
          <div className="border border-border bg-surface-alt rounded p-3">
            <div className="text-xs font-semibold text-fg mb-2 inline-flex items-center gap-2">
              <PlayCircle className="w-3.5 h-3.5 text-accent" /> Execution
            </div>
            <dl className="grid grid-cols-[110px_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
              <dt className="text-fg-muted">Mode</dt>
              <dd className="text-fg">{created.data.mode || '-'}</dd>
              {created.data.goal && (
                <>
                  <dt className="text-fg-muted">Goal</dt>
                  <dd className="text-fg truncate" title={created.data.goal}>{created.data.goal}</dd>
                </>
              )}
              <dt className="text-fg-muted">Project</dt>
              <dd className="text-fg truncate" title={created.data.project_path}>{created.data.project_path || '-'}</dd>
              {!selectedIsCollaboration && (
                <>
                  <dt className="text-fg-muted">Worktree</dt>
                  <dd className="text-fg truncate" title={created.data.worktree_path}>{created.data.worktree_path || '-'}</dd>
                  <dt className="text-fg-muted">Base</dt>
                  <dd className="text-fg font-mono truncate">{created.data.base_branch || '-'} {created.data.base_commit || ''}</dd>
                </>
              )}
            </dl>
          </div>
        )}

        {collaborationEvents.length > 0 && (
          <section className="border border-border bg-surface-alt rounded p-3">
            <div className="text-xs font-semibold text-fg mb-2">Collaboration Timeline</div>
            <div className="space-y-2">
              {collaborationEvents.map((event) => {
                const taskStatus = event.data?.status || event.data?.result?.status || '';
                const message = event.data?.text || event.data?.summary || event.data?.goal || event.data?.artifact?.title || '';
                return (
                  <div key={event.id} className="border-t border-border/60 first:border-t-0 pt-2 first:pt-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-fg">{event.type.replace(/_/g, ' ')}</span>
                      <span className={`text-[10px] uppercase ${statusClass(taskStatus)}`}>{taskStatus || formatTime(event.timestamp)}</span>
                    </div>
                    {message && (
                      <div className="mt-1 text-[11px] text-fg-muted whitespace-pre-wrap line-clamp-4">
                        {message}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        <div className={`border rounded p-3 ${quality.tone}`}>
          <div className="text-xs font-semibold">{quality.label}</div>
          <div className="mt-1 text-[11px] opacity-90">{quality.detail}</div>
          {completed?.data?.verification_command && (
            <div className="mt-2 text-[11px] text-fg-muted truncate" title={completed.data.verification_command}>
              Checked with {completed.data.green_level || 'verification'}.
            </div>
          )}
        </div>

        {context && (
          <div className="border border-border bg-surface-alt rounded p-3">
            <div className="text-xs font-semibold text-fg mb-2">Context Pack</div>
            <pre className="text-xs text-fg-secondary whitespace-pre-wrap max-h-56 overflow-auto">{context.data.repo_map_summary}</pre>
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          <section className="border border-border bg-surface-alt rounded p-3">
            <div className="text-xs font-semibold text-fg mb-2 inline-flex items-center gap-2">
              <ShieldCheck className="w-3.5 h-3.5 text-accent" /> Guardrails
            </div>
            {guardrails.length === 0 ? (
              <div className="text-xs text-fg-muted">No guardrail decisions yet</div>
            ) : guardrails.slice(-8).map((event) => (
              <div key={event.id} className="py-1 border-t border-border/60 first:border-t-0">
                <div className="text-xs text-fg">{event.data.decision || '-'} <span className="text-fg-muted">({event.data.risk || 'low'})</span></div>
                <div className="text-[11px] text-fg-muted">{event.data.reason}</div>
              </div>
            ))}
          </section>

          <section className="border border-border bg-surface-alt rounded p-3">
            <div className="text-xs font-semibold text-fg mb-2 inline-flex items-center gap-2">
              <CheckCircle2 className="w-3.5 h-3.5 text-accent" /> Verification
            </div>
            {verifications.length === 0 ? (
              <div className="text-xs text-fg-muted">No verification result yet</div>
            ) : verifications.map((event) => (
              <div key={event.id} className="py-1 border-t border-border/60 first:border-t-0">
                <div className={`text-xs ${event.data.passed ? 'text-emerald-400' : 'text-red-400'}`}>
                  {event.data.passed ? 'passed' : 'failed'}: {event.data.command}
                </div>
                <div className="text-[11px] text-fg-muted whitespace-pre-wrap">{event.data.summary}</div>
              </div>
            ))}
          </section>
        </div>

        <section className="border border-border bg-surface-alt rounded p-3">
          <div className="text-xs font-semibold text-fg mb-2 inline-flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-accent" /> Review Findings
          </div>
          {findings.length === 0 ? (
            <div className="text-xs text-fg-muted">No review findings yet</div>
          ) : findings.map((event) => (
            <div key={event.id} className="py-1 border-t border-border/60 first:border-t-0">
              <div className="text-xs text-fg">{event.data.severity || 'info'} {event.data.file ? `${event.data.file}:${event.data.line || ''}` : ''}</div>
              <div className="text-[11px] text-fg-muted">{event.data.message}</div>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
