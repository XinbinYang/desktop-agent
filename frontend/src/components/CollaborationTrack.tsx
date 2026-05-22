import React, { useEffect, useState } from 'react';
import {
  ChevronDown, ChevronRight, CheckCircle2, AlertCircle, Loader2, Circle, X,
  FileCode, Terminal, TestTube, GitCompare, FileSearch, Bot, Code2,
  UserRound, Sparkles, Wrench, MessageSquare,
} from 'lucide-react';
import type { EvidenceEntry, CollaborationRecap as RunRecap, RunEvent, TeamProgressEntry as TeamProgressEvent } from '../types';
import {
  buildCollaborationTimeline,
  type CollaborationTimelineItem,
} from '../lib/collaborationTimeline';

const ROLE_LABELS: Record<string, string> = {
  explorer: 'Explorer',
  architect: 'Architect',
  editor: 'Editor',
  verifier: 'Verifier',
  reviewer: 'Reviewer',
};

const ROLE_ORDER = ['explorer', 'architect', 'editor', 'verifier', 'reviewer'];

const EvidenceIcon: React.FC<{ kind: EvidenceEntry['kind'] }> = ({ kind }) => {
  switch (kind) {
    case 'command': return <Terminal className="w-3.5 h-3.5 text-fg-muted" />;
    case 'test': return <TestTube className="w-3.5 h-3.5 text-fg-muted" />;
    case 'diff': return <GitCompare className="w-3.5 h-3.5 text-fg-muted" />;
    case 'review': return <FileSearch className="w-3.5 h-3.5 text-fg-muted" />;
    case 'screenshot': return <FileCode className="w-3.5 h-3.5 text-fg-muted" />;
    default: return <Circle className="w-3.5 h-3.5 text-fg-muted" />;
  }
};

const TimelineIcon: React.FC<{ item: CollaborationTimelineItem }> = ({ item }) => {
  if (item.kind === 'clarification') return <MessageSquare className="w-3.5 h-3.5 text-amber-400" />;
  if (item.kind === 'answer' && item.actor === 'personal') return <Sparkles className="w-3.5 h-3.5 text-accent" />;
  if (item.kind === 'answer') return <UserRound className="w-3.5 h-3.5 text-fg-muted" />;
  if (item.kind === 'tool') return <Wrench className="w-3.5 h-3.5 text-fg-muted" />;
  if (item.kind === 'verification') return <TestTube className="w-3.5 h-3.5 text-fg-muted" />;
  if (item.kind === 'review') return <FileSearch className="w-3.5 h-3.5 text-fg-muted" />;
  if (item.kind === 'edit' || item.kind === 'artifact') return <FileCode className="w-3.5 h-3.5 text-fg-muted" />;
  if (item.actor === 'personal') return <Bot className="w-3.5 h-3.5 text-accent" />;
  if (item.actor === 'coding') return <Code2 className="w-3.5 h-3.5 text-fg-muted" />;
  return <Circle className="w-3.5 h-3.5 text-fg-muted" />;
};

const statusDotClass = (status: CollaborationTimelineItem['status']) => {
  if (status === 'done') return 'bg-success';
  if (status === 'failed') return 'bg-danger';
  if (status === 'waiting') return 'bg-amber-400';
  if (status === 'running') return 'bg-accent animate-pulse';
  return 'bg-fg-muted';
};

/**
 * CollaborationTrack — a compact, collapsible card showing the status of
 * a collaboration run between Personal Agent and Coding Agent (or its
 * sub-roles).
 *
 * Integrates two event sources:
 * 1. **team_progress** — real-time updates from dispatched workers
 * 2. **collaboration_recap** — final summary with evidence ledger
 */
const CollaborationTrack: React.FC<{
  recaps?: RunRecap[];
  teamProgress?: TeamProgressEvent[];
  evidence?: EvidenceEntry[];
  artifacts?: unknown[];
  events?: RunEvent[];
  status?: string;
  pendingClarification?: {
    request_id?: string;
    question: string;
    options?: string[];
    context?: string;
    recommendation?: string;
    answered_by?: string;
    reason?: string;
    confidence?: number;
  } | null;
  onPause?: () => void;
  onCancel?: () => void;
  onAnswerClarification?: (answer: string) => void;
}> = ({
  recaps = [],
  teamProgress = [],
  evidence = [],
  artifacts = [],
  events = [],
  status = '',
  pendingClarification = null,
  onPause,
  onCancel,
  onAnswerClarification,
}) => {
  const [expanded, setExpanded] = useState(true);
  const [clarificationAnswer, setClarificationAnswer] = useState('');
  const timelineItems = buildCollaborationTimeline(events);
  const recentTimeline = timelineItems.slice(-5);
  const currentTimelineItem = timelineItems[timelineItems.length - 1] || null;
  const latestAutoAnswer = [...timelineItems].reverse().find(
    (item) => item.kind === 'answer' && item.rawEvent.data?.answered_by === 'personal_auto',
  );

  useEffect(() => {
    setClarificationAnswer('');
  }, [pendingClarification?.request_id]);

  // Build an ordered role status map from teamProgress events.
  const roleStatus: Record<string, 'running' | 'done' | 'failed'> = {};
  for (const rp of [...teamProgress].reverse()) {
    if (rp.team_role && !roleStatus[rp.team_role]) {
      roleStatus[rp.team_role] = rp.phase;
    }
  }

  // Pick current role (first one still running).
  const currentRole = ROLE_ORDER.find((r) => roleStatus[r] === 'running');
  const activeCount = ROLE_ORDER.filter((r) => roleStatus[r] !== undefined).length;
  const completedCount = ROLE_ORDER.filter((r) => roleStatus[r] === 'done').length;
  const isWaiting = status === 'waiting_clarification' || !!pendingClarification;
  const isRunning = activeCount > 0 && currentRole !== undefined && !isWaiting;

  // Gather all evidence + changed files from recaps.
  const allEvidence = [...evidence, ...recaps.flatMap((r) => r.evidence_ledger)];
  const allChangedFiles = [...new Set(recaps.flatMap((r) => r.changed_files))];
  const hasFailed = status === 'failed' || recaps.some((r) => r.failure_summary);

  return (
    <div className="rounded-lg border border-border bg-surface-alt/90 overflow-hidden my-2">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-border bg-surface-hover/60">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="min-w-0 flex-1 flex items-center gap-2 hover:text-fg transition-colors text-left"
          title={expanded ? 'Collapse' : 'Expand'}
        >
          {expanded
            ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted shrink-0" />
            : <ChevronRight className="w-3.5 h-3.5 text-fg-muted shrink-0" />}
          <span className="chat-text-sm font-semibold text-fg-secondary shrink-0">
            {isWaiting ? 'Coding needs input' : hasFailed ? 'Collaboration failed' : 'Personal ↔ Coding'}
          </span>
          {(isRunning || status === 'running') && <Loader2 className="w-3.5 h-3.5 animate-spin text-accent shrink-0" />}
          {hasFailed && <AlertCircle className="w-3.5 h-3.5 text-danger shrink-0" />}
          {!isRunning && !hasFailed && (completedCount > 0 || status === 'completed') && (
            <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />
          )}
          <span className="chat-text-xs text-fg-muted truncate">
            {pendingClarification?.question || currentTimelineItem?.title || recaps[0]?.one_liner || status || `${activeCount} roles`}
          </span>
        </button>
        <div className="flex items-center gap-1.5 shrink-0">
          {latestAutoAnswer && (
            <span
              className="hidden sm:inline-flex items-center gap-1 rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 chat-text-xs text-accent"
              title={latestAutoAnswer.rawEvent.data?.reason || 'Personal Agent answered automatically'}
            >
              <Sparkles className="w-3 h-3" />
              Auto
            </span>
          )}
          {activeCount > 0 && (
            <span className="chat-text-xs text-fg-muted tabular-nums px-1">
              {completedCount}/{activeCount}
            </span>
          )}
          {isRunning && onPause && (
            <button
              type="button"
              onClick={onPause}
              className="inline-flex items-center gap-1 rounded-md border border-border-subtle bg-surface px-2 py-1 chat-text-xs text-fg-secondary hover:text-fg hover:bg-surface-hover"
              title="Pause"
            >
              <Circle className="w-3 h-3" />
              Pause
            </button>
          )}
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="inline-flex items-center gap-1 rounded-md border border-danger/35 bg-danger/10 px-2 py-1 chat-text-xs text-danger hover:bg-danger/15"
              title="Cancel"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {expanded && (
        <div className="px-3 py-2 space-y-2 max-h-80 overflow-y-auto">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded border border-border-subtle bg-surface px-2 py-1.5">
              <div className="flex items-center gap-1.5 chat-text-xs text-fg-muted">
                <Bot className="w-3.5 h-3.5 text-accent" />
                Personal
              </div>
              <div className="mt-1 chat-text-xs text-fg-secondary truncate">
                {latestAutoAnswer ? 'Auto arbitration ready' : 'Delegating and coordinating'}
              </div>
            </div>
            <div className="rounded border border-border-subtle bg-surface px-2 py-1.5">
              <div className="flex items-center gap-1.5 chat-text-xs text-fg-muted">
                <Code2 className="w-3.5 h-3.5 text-fg-secondary" />
                Coding
              </div>
              <div className="mt-1 chat-text-xs text-fg-secondary truncate">
                {isWaiting ? 'Waiting for clarification' : hasFailed ? 'Needs attention' : status === 'completed' ? 'Finished' : 'Working'}
              </div>
            </div>
          </div>

          {pendingClarification && (
            <div className="rounded border border-accent/30 bg-accent/10 px-2.5 py-2 space-y-2">
              <div className="chat-text-sm font-medium text-fg">
                {pendingClarification.question}
              </div>
              {pendingClarification.context && (
                <div className="chat-text-xs text-fg-muted">
                  {pendingClarification.context}
                </div>
              )}
              {pendingClarification.options && pendingClarification.options.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {pendingClarification.options.map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setClarificationAnswer(option)}
                      className="rounded-md border border-border-subtle bg-surface px-2 py-1 chat-text-xs text-fg-secondary hover:text-fg hover:bg-surface-hover"
                    >
                      {option}
                    </button>
                  ))}
                </div>
              )}
              {pendingClarification.recommendation && (
                <div className="chat-text-xs text-fg-muted">
                  Recommended: {pendingClarification.recommendation}
                </div>
              )}
              <div className="flex items-center gap-2">
                <input
                  value={clarificationAnswer}
                  onChange={(event) => setClarificationAnswer(event.target.value)}
                  className="min-w-0 flex-1 rounded-md border border-border bg-surface px-2 py-1.5 chat-text-sm text-fg outline-none focus:border-accent"
                  placeholder="Answer for Coding Agent"
                />
                <button
                  type="button"
                  disabled={!clarificationAnswer.trim() || !onAnswerClarification}
                  onClick={() => {
                    const answer = clarificationAnswer.trim();
                    if (!answer || !onAnswerClarification) return;
                    onAnswerClarification(answer);
                    setClarificationAnswer('');
                  }}
                  className="inline-flex items-center gap-1 rounded-md border border-accent/40 bg-accent/15 px-2.5 py-1.5 chat-text-xs text-accent hover:bg-accent/20 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Send
                </button>
              </div>
            </div>
          )}

          {recentTimeline.length > 0 && (
            <div className="space-y-1.5">
              <div className="chat-text-xs text-fg-muted font-medium">Live collaboration</div>
              {recentTimeline.map((item) => (
                <div key={item.id} className="flex gap-2 rounded border border-border-subtle bg-surface px-2 py-1.5">
                  <div className="relative mt-0.5 shrink-0">
                    <TimelineIcon item={item} />
                    <span className={`absolute -right-0.5 -bottom-0.5 h-1.5 w-1.5 rounded-full ${statusDotClass(item.status)}`} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="chat-text-xs font-medium text-fg-secondary truncate">{item.title}</span>
                      {item.rawEvent.data?.answered_by === 'personal_auto' && (
                        <span className="shrink-0 rounded border border-accent/30 bg-accent/10 px-1 py-0.5 text-[10px] leading-none text-accent">
                          personal_auto
                        </span>
                      )}
                    </div>
                    {item.detail && (
                      <div className="mt-0.5 chat-text-xs text-fg-muted truncate" title={item.detail}>
                        {item.detail}
                      </div>
                    )}
                    {item.rawEvent.data?.reason && (
                      <div className="mt-0.5 chat-text-xs text-fg-muted truncate" title={item.rawEvent.data.reason}>
                        Reason: {item.rawEvent.data.reason}
                        {typeof item.rawEvent.data?.confidence === 'number'
                          ? ` · ${Math.round(item.rawEvent.data.confidence * 100)}%`
                          : ''}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {ROLE_ORDER.map((role) => {
            const status = roleStatus[role];
            if (!status) return null;
            return (
              <div key={role} className="flex items-center gap-2 chat-text-sm">
                {status === 'running' && <Loader2 className="w-3.5 h-3.5 animate-spin text-accent shrink-0" />}
                {status === 'done' && <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0" />}
                {status === 'failed' && <AlertCircle className="w-3.5 h-3.5 text-danger shrink-0" />}
                <span className={
                  status === 'done' ? 'text-fg-muted'
                    : status === 'failed' ? 'text-danger'
                      : 'text-fg'
                }>
                  {ROLE_LABELS[role] || role}
                </span>
              </div>
            );
          })}

          {/* Changed files */}
          {allChangedFiles.length > 0 && (
            <div className="pt-1">
              <span className="chat-text-xs text-fg-muted font-medium">Changed files:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {allChangedFiles.slice(0, 8).map((f) => (
                  <span key={f} className="inline-flex items-center gap-1 rounded bg-surface-hover px-1.5 py-0.5 chat-text-xs text-fg-secondary">
                    <FileCode className="w-3 h-3" />
                    {f.split('/').pop()}
                  </span>
                ))}
                {allChangedFiles.length > 8 && (
                  <span className="chat-text-xs text-fg-muted">+{allChangedFiles.length - 8} more</span>
                )}
              </div>
            </div>
          )}

          {/* Evidence ledger */}
          {allEvidence.length > 0 && (
            <div className="pt-1">
              <span className="chat-text-xs text-fg-muted font-medium">Evidence:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {allEvidence.slice(0, 6).map((ev, i) => (
                  <span
                    key={`${ev.kind}-${i}`}
                    className="inline-flex items-center gap-1 rounded bg-surface-hover px-1.5 py-0.5 chat-text-xs text-fg-secondary"
                    title={ev.command || ev.label}
                  >
                    <EvidenceIcon kind={ev.kind} />
                    {ev.label.slice(0, 40)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {artifacts.length > 0 && (
            <div className="pt-1">
              <span className="chat-text-xs text-fg-muted font-medium">Artifacts:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {artifacts.slice(0, 6).map((artifact, i) => {
                  const item = artifact as { title?: string; path?: string; type?: string };
                  return (
                    <span key={`${item.path || item.title || i}`} className="inline-flex items-center gap-1 rounded bg-surface-hover px-1.5 py-0.5 chat-text-xs text-fg-secondary">
                      <FileCode className="w-3 h-3" />
                      {(item.title || item.path || item.type || 'artifact').slice(0, 40)}
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          {/* Failure */}
          {hasFailed && recaps.filter((r) => r.failure_summary).map((r) => (
            <div key={r.run_id} className="rounded bg-danger/10 px-2 py-1.5 chat-text-xs text-danger">
              {r.failure_summary}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export { CollaborationTrack };
export default CollaborationTrack;
