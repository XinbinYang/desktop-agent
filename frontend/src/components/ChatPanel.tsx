import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Send, Image, Loader2, Square, ChevronDown, ChevronRight, RotateCcw, Mic, MicOff, Search, ArrowDown, Shield, ShieldOff, BookOpen, Check, Circle, CheckCircle2, AlertCircle, Bot, Code2, FolderOpen, Pause, Play, X, Maximize2, Zap } from 'lucide-react';
import { Virtuoso, VirtuosoHandle, type IndexLocationWithAlign, type ListRange, type StateSnapshot } from 'react-virtuoso';
import { useTranslation } from 'react-i18next';
import {
  ChatMessage,
  ToolCall,
  AssistantBlock,
  ToolSummary,
  ClientChatMode,
  ThinkingIntensity,
  AgentType,
  PlanQuestion,
  PlanDecisionAnswer,
  PlanState,
  PlanTodo,
  FileEdit,
  RunEvent,
  ContextUsage,
  ConversationCheckpoint,
  TaskGuidanceItem,
  CollaborationState,
  ImageAttachment,
} from '../types';
import { API_BASE } from '../config';
import { useTheme } from '../hooks/useTheme';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ToolCallView } from './ToolCallView';
import { FileEditView } from './FileEditView';
import { SlashCommandMenu } from './SlashCommandMenu';
import { AtMentionMenu } from './AtMentionMenu';
import { ContextMeter } from './ContextMeter';
import { RewindModal } from './RewindModal';
import { PersonalChatSurface } from './chat/PersonalChatSurface';
import { AgentRunningStatus } from './chat/AgentRunningStatus';
import { CollaborationTrack } from './CollaborationTrack';
import { collaborationEventsForRun } from '../lib/collaborationTimeline';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './ui/DropdownMenu';
import { RevealableInlineCode } from './RevealPathAction';
import {
  buildTimelineEvents,
  type TimelineEvent,
  type TimelineRenderMode,
  type TimelineToolEvent,
} from '../lib/timelineEvents';
import { isInternalToolName } from '../lib/internalTools';
import {
  imageAttachmentFromBlock,
  imageAttachmentLabel,
  imageAttachmentSrc,
} from '../lib/imageAttachments';

interface ChatPanelProps {
  sessionId?: string;
  messages: ChatMessage[];
  toolCalls: ToolCall[];
  fileEdits?: FileEdit[];
  runEvents?: RunEvent[];
  onSend: (
    text: string,
    imageBase64?: string,
    overrides?: { chatMode?: ClientChatMode; thinkingIntensity?: ThinkingIntensity }
  ) => void;
  onStop?: () => void;
  onRetry?: () => void;
  isRunning: boolean;
  onDraftSave?: (text: string) => void;
  onDraftLoad?: () => Promise<string | undefined>;
  onDraftClear?: () => void;
  chatMode: ClientChatMode;
  onChatModeChange: (mode: ClientChatMode) => void;
  thinkingIntensity: ThinkingIntensity;
  onThinkingIntensityChange: (intensity: ThinkingIntensity) => void;
  planState: PlanState;
  collaborationState?: CollaborationState;
  onApprovePlan: () => void;
  onBuildPlan: () => void;
  onPauseBuild: () => void;
  onEndBuild: () => void;
  onPauseCollaboration?: () => void;
  onCancelCollaboration?: () => void;
  onAnswerCollaborationClarification?: (answer: string) => void;
  onRejectPlan: () => void;
  onUpdatePlanDecision: (questionId: string, selected: string[]) => void;
  onSubmitPlanDecisions: (answers: PlanDecisionAnswer[]) => void;
  onViewPlan?: () => void;
  onCommand?: (command: string, args: string) => void;
  contextUsage?: ContextUsage | null;
  checkpoints?: ConversationCheckpoint[];
  taskGuidanceItems?: TaskGuidanceItem[];
  onQueueTaskGuidance?: (text: string, imageBase64?: string, options?: { applyNow?: boolean }) => void;
  onApplyTaskGuidance?: () => void;
  onDeleteTaskGuidance?: (id: string) => void;
  onClearTaskGuidance?: () => void;
  onCompact?: (force?: boolean, focus?: string) => void;
  onClearSession?: () => void;
  onLoadCheckpoints?: () => Promise<ConversationCheckpoint[]>;
  onRewindToCheckpoint?: (checkpointId: string) => void;
  rewindOpen?: boolean;
  onRewindOpenChange?: (open: boolean) => void;
  projectOpen?: boolean;
  projectPath?: string | null;
  fileTree?: any[];
  agentType?: AgentType;
  projectName?: string;
  assistantDisplayName?: string;
}

type OutputMode = 'concise' | 'balanced' | 'verbose';
type SandboxMode = 'sandbox' | 'unrestricted';

interface ImagePreviewState {
  src: string;
  alt: string;
}

interface ChatScrollMemory {
  atBottom?: boolean;
  messageCount: number;
  range?: ListRange;
  snapshot?: StateSnapshot;
  updatedAt: number;
}

const chatScrollMemoryBySession = new Map<string, ChatScrollMemory>();

const COMMAND_KEYS = new Set(['ArrowDown', 'ArrowUp', 'Enter', 'Escape']);
const DIRECT_COMMANDS = new Set([
  'clear',
  'reset',
  'new',
  'help',
  'compact',
  'rewind',
  'context',
  'config',
  'screenshot',
  'skills',
]);
const ARG_COMMANDS = new Set(['model', 'role', 'project']);

const THINKING_LEVELS: ThinkingIntensity[] = ['low', 'medium', 'high'];
const THINKING_LABELS: Record<ThinkingIntensity, string> = {
  low: 'LOW',
  medium: 'MEDIUM',
  high: 'HIGH',
};
const CHAT_INPUT_MIN_HEIGHT = 48;
const CHAT_INPUT_MAX_HEIGHT = 144;

function parseSlashInput(value: string): { command: string; args: string } | null {
  const trimmed = value.trim();
  if (!trimmed.startsWith('/') || trimmed === '/') return null;
  const match = trimmed.match(/^\/([A-Za-z][\w-]*)(?:\s+([\s\S]*))?$/);
  if (!match) return null;
  return {
    command: match[1].toLowerCase(),
    args: (match[2] || '').trim(),
  };
}

function getInitialOutputMode(): OutputMode {
  try {
    const v = localStorage.getItem('desktop-agent-output-mode');
    if (v === 'concise' || v === 'balanced' || v === 'verbose') return v;
  } catch { /* ignore */ }
  return 'concise';
}

function getInitialNoiseFilter(): boolean {
  try {
    const raw = localStorage.getItem('desktop-agent-hide-tool-noise');
    if (raw === '0') return false;
  } catch { /* ignore */ }
  return true;
}

function getPersonalChatV2Enabled(): boolean {
  try {
    return localStorage.getItem('desktop-agent-personal-chat-v2') !== '0';
  } catch {
    return true;
  }
}

let sandboxModeCache: SandboxMode | null = null;
let sandboxModePromise: Promise<SandboxMode | null> | null = null;
const sandboxModeSubscribers = new Set<(mode: SandboxMode) => void>();

function publishSandboxMode(mode: SandboxMode) {
  sandboxModeCache = mode;
  for (const subscriber of Array.from(sandboxModeSubscribers)) {
    subscriber(mode);
  }
}

function loadSandboxModeOnce(): Promise<SandboxMode | null> {
  if (sandboxModeCache) return Promise.resolve(sandboxModeCache);
  if (!sandboxModePromise) {
    sandboxModePromise = fetch(`${API_BASE}/api/settings`)
      .then((res) => res.json())
      .then((data) => {
        const mode = data.settings?.sandbox_mode;
        if (mode === 'sandbox' || mode === 'unrestricted') {
          sandboxModeCache = mode;
          return mode as SandboxMode;
        }
        return null;
      })
      .catch(() => null)
      .finally(() => {
        sandboxModePromise = null;
      });
  }
  return sandboxModePromise;
}

function isNoisyToolBlock(block: Extract<AssistantBlock, { type: 'tool_call' }>): boolean {
  if (isInternalToolName(block.name)) return true;
  if (block.status !== 'success') return false;
  const n = (block.name || '').toLowerCase();
  return n === 'file_read' || n === 'file_search' || n === 'file_list';
}

function planPhaseLabel(phase: PlanState['phase']): string {
  const labels: Record<PlanState['phase'], string> = {
    idle: 'Idle',
    clarifying: 'Clarifying',
    planning: 'Planning',
    awaiting_decision: 'Awaiting decision',
    awaiting_approval: 'Awaiting approval',
    approved_waiting_build: 'Approved, waiting Build',
    executing: 'Executing',
    completed: 'Completed',
  };
  return labels[phase] || phase;
}

/** Cursor-style list icon: three lines with dots (top/bottom left, middle right). */
function PlanModeIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <circle cx="3" cy="4" r="1.25" fill="currentColor" />
      <line x1="5.2" y1="4" x2="13" y2="4" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
      <line x1="3" y1="8" x2="10.8" y2="8" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
      <circle cx="13" cy="8" r="1.25" fill="currentColor" />
      <circle cx="3" cy="12" r="1.25" fill="currentColor" />
      <line x1="5.2" y1="12" x2="13" y2="12" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
    </svg>
  );
}

/** Friendly elapsed-time label: <60s → "8s", ≥60s → "2m 5s". */
function formatThinkDuration(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  if (totalSec < 60) return `${totalSec}s`;
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return s === 0 ? `${m}m` : `${m}m ${s}s`;
}

const EmptyStatusChip: React.FC<{
  children: React.ReactNode;
  tone?: 'accent' | 'success' | 'neutral';
  title?: string;
}> = ({ children, tone = 'neutral', title }) => {
  const toneClass =
    tone === 'success'
      ? 'border-success/25 bg-success/10 text-success'
      : tone === 'accent'
        ? 'border-accent/25 bg-accent/10 text-accent'
        : 'border-border-subtle bg-surface text-fg-secondary';

  return (
    <div
      className={`max-w-full rounded-md border px-2.5 py-1 chat-text-xs font-medium ${toneClass}`}
      title={title}
    >
      <span className="block truncate">{children}</span>
    </div>
  );
};

const EmptyChatWelcome: React.FC<{
  agentType: AgentType;
  chatMode: ClientChatMode;
  projectName?: string;
  assistantDisplayName?: string;
}> = ({ agentType, chatMode, projectName, assistantDisplayName }) => {
  const { t } = useTranslation();
  const isCoding = agentType === 'coding';
  const visibleProjectName = isCoding ? projectName : undefined;
  const AgentIcon = isCoding ? Code2 : Bot;
  const typeLabel = isCoding ? t('chat.empty.codingAgent') : t('chat.empty.personalAgent');
  const agentLabel = isCoding ? typeLabel : (assistantDisplayName?.trim() || typeLabel);
  const modeLabel = chatMode === 'plan' ? t('chat.empty.planMode') : t('chat.empty.agentMode');
  const title = visibleProjectName
    ? t('chat.empty.projectReady', { projectName: visibleProjectName })
    : t('chat.empty.ready');

  return (
    <div
      data-testid="empty-chat-welcome"
      className="flex h-full min-h-[220px] items-center justify-center px-[var(--chat-space-xl)] py-8 text-fg"
    >
      <div className="w-full max-w-md text-center">
        <div
          className={`mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl border ${
            isCoding
              ? 'border-success/30 bg-success/10 text-success'
              : 'border-accent/30 bg-accent/10 text-accent'
          }`}
          aria-hidden
        >
          <AgentIcon className="h-6 w-6" />
        </div>
        <h2 className="chat-text-lg font-semibold text-fg">{title}</h2>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <EmptyStatusChip tone={isCoding ? 'success' : 'accent'}>{agentLabel}</EmptyStatusChip>
          {!isCoding && agentLabel !== typeLabel && <EmptyStatusChip tone="neutral">{typeLabel}</EmptyStatusChip>}
          <EmptyStatusChip tone={chatMode === 'plan' ? 'accent' : 'neutral'}>{modeLabel}</EmptyStatusChip>
          {visibleProjectName && (
            <EmptyStatusChip title={visibleProjectName}>
              <span className="inline-flex min-w-0 items-center gap-1.5">
                <FolderOpen className="h-3 w-3 shrink-0" />
                <span className="truncate">{visibleProjectName}</span>
              </span>
            </EmptyStatusChip>
          )}
        </div>
      </div>
    </div>
  );
};

const OPTION_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

function planAnswerLabel(question: PlanQuestion | undefined, answer: PlanDecisionAnswer): string {
  if (answer.skipped) return 'Skipped; use best default';
  const labels = (answer.selected || []).map((id) => question?.options.find((o) => o.id === id)?.label || id);
  if (answer.other_text?.trim()) labels.push(`Other: ${answer.other_text.trim()}`);
  return labels.length > 0 ? labels.join(', ') : 'No answer recorded';
}

const PlanAnswersBlock: React.FC<{
  questions: PlanQuestion[];
  answers: PlanDecisionAnswer[];
}> = ({ questions, answers }) => (
  <div className="my-2 rounded-lg border border-border bg-surface/80 px-4 py-3">
    <div className="chat-text-sm text-fg-muted mb-3">Answers</div>
    <div className="space-y-3">
      {answers.map((answer) => {
        const question = questions.find((q) => q.id === answer.question_id);
        return (
          <div key={answer.question_id} className="chat-text-sm">
            <div className="font-medium text-fg-secondary">{question?.prompt || answer.question_id}</div>
            <div className="mt-1 text-fg">{planAnswerLabel(question, answer)}</div>
          </div>
        );
      })}
    </div>
  </div>
);

const TaskGuidanceQueueCard: React.FC<{
  items: TaskGuidanceItem[];
  isRunning: boolean;
  onApply?: () => void;
  onDelete?: (id: string) => void;
  onClear?: () => void;
}> = ({ items, isRunning, onApply, onDelete, onClear }) => {
  const visible = isRunning
    ? items.filter((item) => item.status === 'queued' || item.status === 'applied')
    : [];
  if (!isRunning || visible.length === 0) return null;

  const actionableCount = visible.filter((item) => item.status === 'queued').length;
  const waitingCount = visible.filter((item) => item.status === 'applied').length;

  return (
    <div className="mb-2 rounded-md border border-accent/25 bg-accent/5 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="chat-text-xs font-semibold text-fg">任务引导 ({visible.length})</div>
          <div className="chat-text-xs text-fg-muted">
            {waitingCount > 0 && actionableCount > 0
              ? `${actionableCount} 条已排队，${waitingCount} 条已提交等待读取`
              : waitingCount > 0
                ? `已提交，等待 Agent 读取 ${waitingCount} 条`
                : `${actionableCount} 条已排队`}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onApply}
            disabled={!isRunning || actionableCount === 0}
            className="chat-text-xs rounded-md bg-accent/85 px-2.5 py-1 font-medium text-fg-on-accent hover:bg-accent disabled:bg-surface-alt disabled:text-fg-muted"
          >
            提交排队项
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={visible.length === 0}
            className="chat-text-xs rounded-md border border-border-subtle px-2 py-1 text-fg-muted hover:text-fg disabled:opacity-45"
          >
            清空
          </button>
        </div>
      </div>
      <div className="mt-2 space-y-1.5">
        {visible.map((item) => {
          const statusText =
            item.status === 'applied'
              ? '已提交，待读取'
              : '已排队';
          const preview = item.text?.trim() || (item.image_base64 ? 'Image attached' : '');
          return (
            <div key={item.id} className="flex items-center gap-2 rounded-md bg-surface/70 px-2 py-1.5">
              <span className="shrink-0 rounded border border-border-subtle px-1.5 py-0.5 chat-text-xs text-fg-muted">
                {statusText}
              </span>
              <span className="min-w-0 flex-1 truncate chat-text-xs text-fg-secondary" title={preview}>
                {preview}{item.truncated ? ' ...' : ''}
              </span>
              <button
                type="button"
                onClick={() => onDelete?.(item.id)}
                className="shrink-0 rounded p-1 text-fg-muted hover:bg-surface-hover hover:text-fg"
                aria-label="Remove guidance"
                title="Remove guidance"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const CreatingPlanStatus: React.FC = () => (
  <div className="rounded-md border border-[color:var(--plan-pill-border)] bg-surface/90 px-3 py-2 chat-text-sm text-fg-secondary flex items-center gap-2">
    <Loader2 className="w-3.5 h-3.5 animate-spin text-[color:var(--plan-pill-bg)]" />
    <span>Creating plan</span>
  </div>
);

const PlanTodoStatusIcon: React.FC<{ status: PlanTodo['status'] }> = ({ status }) => {
  if (status === 'completed') return <CheckCircle2 className="w-4 h-4 text-success" />;
  if (status === 'blocked' || status === 'cancelled') return <AlertCircle className="w-4 h-4 text-danger" />;
  if (status === 'in_progress') return <Loader2 className="w-4 h-4 animate-spin text-accent" />;
  return <Circle className="w-4 h-4 text-fg-muted" />;
};

const PlanExecutionCard: React.FC<{
  goal: string;
  todos: PlanTodo[];
  phase?: PlanState['phase'];
  compact?: boolean;
  onPause?: () => void;
  onEnd?: () => void;
  onContinue?: () => void;
}> = ({ goal, todos, phase = 'executing', compact = false, onPause, onEnd, onContinue }) => {
  const [expanded, setExpanded] = useState(true);
  const inProgressIndex = todos.findIndex((t) => t.status === 'in_progress');
  const pendingIndex = todos.findIndex((t) => t.status === 'pending');
  const currentIndex = inProgressIndex >= 0 ? inProgressIndex : pendingIndex >= 0 ? pendingIndex : 0;
  const active = todos[currentIndex] || todos[0];
  const completed = todos.filter((t) => t.status === 'completed').length;
  const isPaused = phase === 'approved_waiting_build';
  const isRunning = phase === 'executing' && inProgressIndex >= 0;
  const progressIndex = isRunning ? currentIndex + 1 : completed;
  const allDone = todos.length > 0 && completed === todos.length;
  const hasControls = (phase === 'executing' || isPaused) && !!(onPause || onEnd || onContinue);

  return (
    <div className={`rounded-lg border border-border bg-surface-alt/90 overflow-hidden ${compact ? 'my-2' : ''}`}>
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-border bg-surface-hover/60">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="min-w-0 flex-1 flex items-center gap-2 hover:text-fg transition-colors text-left"
          title={expanded ? 'Collapse todos' : 'Expand todos'}
        >
          {expanded
            ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted shrink-0" />
            : <ChevronRight className="w-3.5 h-3.5 text-fg-muted shrink-0" />}
          <span className="chat-text-sm font-semibold text-fg-secondary shrink-0">Build</span>
          {isRunning && <Loader2 className="w-3.5 h-3.5 animate-spin text-accent shrink-0" />}
          {isPaused && <Pause className="w-3.5 h-3.5 text-warning shrink-0" />}
          <span className="chat-text-sm text-fg truncate">{goal || 'Plan execution'}</span>
        </button>
        <div className="flex items-center gap-1.5 shrink-0">
          {todos.length > 0 && (
            <span className="chat-text-xs text-fg-muted tabular-nums px-1">
              {Math.min(progressIndex, todos.length)}/{todos.length}
            </span>
          )}
          {hasControls && isPaused && onContinue && (
            <button
              type="button"
              onClick={onContinue}
              className="inline-flex items-center gap-1 rounded-md border border-border-subtle bg-surface px-2 py-1 chat-text-xs text-fg-secondary hover:text-fg hover:bg-surface-hover"
              title="Continue Build"
              aria-label="Continue Build"
            >
              <Play className="w-3.5 h-3.5" />
              Continue
            </button>
          )}
          {hasControls && phase === 'executing' && onPause && (
            <button
              type="button"
              onClick={onPause}
              className="inline-flex items-center gap-1 rounded-md border border-border-subtle bg-surface px-2 py-1 chat-text-xs text-fg-secondary hover:text-fg hover:bg-surface-hover"
              title="Pause Build"
              aria-label="Pause Build"
            >
              <Pause className="w-3.5 h-3.5" />
              Pause
            </button>
          )}
          {hasControls && onEnd && (
            <button
              type="button"
              onClick={onEnd}
              className="inline-flex items-center gap-1 rounded-md border border-danger/35 bg-danger/10 px-2 py-1 chat-text-xs text-danger hover:bg-danger/15"
              title="End Build"
              aria-label="End Build"
            >
              <X className="w-3.5 h-3.5" />
              End
            </button>
          )}
        </div>
      </div>
      {!expanded && active && !allDone && (
        <div className="flex items-center gap-2 px-3 py-2 chat-text-sm">
          <PlanTodoStatusIcon status={active.status} />
          <span className="text-fg truncate">{active.title}</span>
        </div>
      )}
      {expanded && (
        <div className="px-3 py-2 space-y-2 max-h-60 overflow-y-auto">
          {todos.map((todo) => (
            <div key={todo.id} className="flex items-start gap-2 chat-text-sm">
              <PlanTodoStatusIcon status={todo.status} />
              <span className={
                todo.status === 'completed'
                  ? 'text-fg-muted line-through'
                  : todo.status === 'in_progress'
                    ? 'text-fg'
                    : todo.status === 'blocked' || todo.status === 'cancelled'
                      ? 'text-danger'
                      : 'text-fg-secondary'
              }>
                {todo.title}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const PlanQuestionsDock: React.FC<{
  questions: PlanQuestion[];
  onSubmit: (answers: PlanDecisionAnswer[]) => void;
}> = ({ questions, onSubmit }) => {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, {
    selected: string[];
    other: boolean;
    otherText: string;
    skipped: boolean;
  }>>({});

  useEffect(() => {
    const init: Record<string, { selected: string[]; other: boolean; otherText: string; skipped: boolean }> = {};
    questions.forEach((q) => {
      init[q.id] = answers[q.id] || { selected: [], other: false, otherText: '', skipped: false };
    });
    setAnswers(init);
    setIndex((prev) => Math.min(prev, Math.max(questions.length - 1, 0)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questions.map((q) => q.id).join('|')]);

  if (questions.length === 0) return null;
  const question = questions[Math.min(index, questions.length - 1)];
  const answer = answers[question.id] || { selected: [], other: false, otherText: '', skipped: false };
  const otherNeedsText = answer.other && !answer.otherText.trim();
  const canContinue = answer.skipped || answer.selected.length > 0 || (answer.other && answer.otherText.trim().length > 0);
  const isLast = index === questions.length - 1;

  const updateAnswer = (next: Partial<typeof answer>) => {
    setAnswers((prev) => ({
      ...prev,
      [question.id]: { ...answer, ...next },
    }));
  };

  const selectOption = (id: string) => {
    if (question.allow_multiple) {
      const selected = answer.selected.includes(id)
        ? answer.selected.filter((x) => x !== id)
        : [...answer.selected, id];
      updateAnswer({ selected, skipped: false });
      return;
    }
    updateAnswer({ selected: [id], other: false, otherText: '', skipped: false });
  };

  const toggleOther = () => {
    if (question.allow_multiple) {
      updateAnswer({ other: !answer.other, skipped: false });
      return;
    }
    updateAnswer({ selected: [], other: true, skipped: false });
  };

  const toPayload = (source: typeof answers): PlanDecisionAnswer[] => questions.map((q) => {
    const a = source[q.id] || { selected: [], other: false, otherText: '', skipped: false };
    return {
      question_id: q.id,
      selected: a.skipped ? [] : a.selected,
      other_text: a.skipped || !a.other ? '' : a.otherText.trim(),
      skipped: a.skipped,
    };
  });

  const continueOrSubmit = () => {
    if (!canContinue || otherNeedsText) return;
    if (!isLast) {
      setIndex((prev) => Math.min(prev + 1, questions.length - 1));
      return;
    }
    onSubmit(toPayload(answers));
  };

  const skipQuestion = () => {
    const nextAnswers = {
      ...answers,
      [question.id]: { selected: [], other: false, otherText: '', skipped: true },
    };
    setAnswers(nextAnswers);
    if (!isLast) {
      setIndex((prev) => Math.min(prev + 1, questions.length - 1));
      return;
    }
    onSubmit(toPayload(nextAnswers));
  };

  return (
    <div className="mb-3 rounded-lg border border-[color:var(--plan-pill-border)] bg-surface/95 shadow-2xl overflow-hidden" role="dialog" aria-label="Plan questions">
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-border-subtle">
        <div className="flex items-center gap-2">
          <PlanModeIcon className="text-[color:var(--plan-pill-bg)]" />
          <span className="chat-text-sm font-semibold text-fg">Questions</span>
        </div>
        <div className="flex items-center gap-2 chat-text-xs text-fg-muted">
          <span>{index + 1} of {questions.length}</span>
          {questions.length > 1 && (
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => setIndex((v) => Math.max(0, v - 1))} disabled={index === 0} className="disabled:opacity-35 hover:text-fg" aria-label="Previous question">
                <ChevronDown className="w-3 h-3 rotate-180" />
              </button>
              <button type="button" onClick={() => setIndex((v) => Math.min(questions.length - 1, v + 1))} disabled={index === questions.length - 1} className="disabled:opacity-35 hover:text-fg" aria-label="Next question">
                <ChevronDown className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="px-4 py-3">
        <div className="chat-text-sm font-semibold text-fg mb-3">
          {index + 1}. {question.prompt}
        </div>
        <div className="space-y-2">
          {question.options.map((option, optionIndex) => {
            const selected = answer.selected.includes(option.id);
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => selectOption(option.id)}
                className={`w-full flex items-start gap-2 text-left rounded-md px-2 py-1.5 chat-text-sm transition-colors ${
                  selected ? 'bg-accent/15 text-fg border border-accent/35' : 'text-fg-secondary hover:bg-surface-hover border border-transparent'
                }`}
              >
                <span className="mt-0.5 w-5 h-5 rounded border border-border bg-surface-alt text-[11px] font-semibold text-fg-secondary flex items-center justify-center shrink-0">
                  {OPTION_LETTERS[optionIndex]}
                </span>
                <span>{option.label}</span>
              </button>
            );
          })}
          <button
            type="button"
            onClick={toggleOther}
            className={`w-full flex items-start gap-2 text-left rounded-md px-2 py-1.5 chat-text-sm transition-colors ${
              answer.other ? 'bg-accent/15 text-fg border border-accent/35' : 'text-fg-muted hover:bg-surface-hover border border-transparent'
            }`}
          >
            <span className="mt-0.5 w-5 h-5 rounded border border-border bg-surface-alt text-[11px] font-semibold text-fg-secondary flex items-center justify-center shrink-0">
              {OPTION_LETTERS[question.options.length]}
            </span>
            <span>Other...</span>
          </button>
          {answer.other && (
            <input
              value={answer.otherText}
              onChange={(e) => updateAnswer({ otherText: e.target.value, skipped: false })}
              placeholder="Describe your preference"
              className="w-full mt-1 bg-surface-input border border-border rounded-md px-3 py-2 chat-text-sm text-fg outline-none focus:border-accent"
              autoFocus
            />
          )}
        </div>
      </div>
      <div className="flex items-center justify-end gap-2 px-3 py-2 border-t border-border-subtle">
        <button type="button" onClick={skipQuestion} className="chat-text-xs text-fg-muted hover:text-fg-secondary">
          Skip Esc
        </button>
        <button
          type="button"
          onClick={continueOrSubmit}
          disabled={!canContinue || otherNeedsText}
          className="chat-text-xs font-semibold rounded-md bg-[color:var(--plan-pill-bg)] text-[color:var(--plan-pill-fg)] px-3 py-1.5 disabled:opacity-45 disabled:cursor-not-allowed hover:brightness-110"
        >
          Continue
        </button>
      </div>
    </div>
  );
};

/**
 * Live, auto-collapsing thinking/reasoning block (VSCode Claude-Code style).
 * - In progress: auto-expanded fixed-height window streaming tokens, pinned
 *   to the bottom, with an animated indicator and a running elapsed timer.
 * - Complete: auto-collapses to a single "Thought for Ns" line; clicking
 *   re-expands the full reasoning. A manual toggle overrides the auto state.
 */
const ReasoningBlock: React.FC<{
  text: string;
  complete?: boolean;
  startedAt?: number;
  endedAt?: number;
}> = ({ text, complete, startedAt, endedAt }) => {
  // null = follow auto behaviour; true/false = user explicitly toggled.
  const [userToggled, setUserToggled] = useState<boolean | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const inProgress = !complete;
  const expanded = userToggled ?? inProgress;

  // Tick once a second while thinking so the timer updates live.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (complete) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [complete]);

  const hasTimer = typeof startedAt === 'number';
  const elapsedMs = hasTimer
    ? (complete ? (endedAt ?? now) : now) - (startedAt as number)
    : 0;

  // Keep the live window pinned to the latest tokens.
  useEffect(() => {
    if (!complete && expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [text, complete, expanded]);

  const headerLabel = inProgress
    ? 'Thinking'
    : hasTimer
      ? `Thought for ${formatThinkDuration(elapsedMs)}`
      : 'Thought';

  return (
    <div className="my-[var(--chat-space-sm)] rounded-md border border-border bg-surface/60 overflow-hidden border-l-2 border-l-info/70">
      <button
        type="button"
        onClick={() => setUserToggled((v) => !(v ?? expanded))}
        className="w-full flex items-center gap-1.5 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-sm text-fg-secondary hover:text-fg hover:bg-surface-hover transition-colors"
      >
        {inProgress ? (
          <span className="flex items-center gap-0.5 text-info" aria-hidden>
            <span className="think-dot w-1 h-1 rounded-full bg-current" />
            <span className="think-dot w-1 h-1 rounded-full bg-current" />
            <span className="think-dot w-1 h-1 rounded-full bg-current" />
          </span>
        ) : expanded ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronRight className="w-3 h-3" />
        )}
        <span className="font-medium">{headerLabel}</span>
        {inProgress && hasTimer && (
          <span className="text-fg-muted ml-1 chat-text-xs tabular-nums">
            {formatThinkDuration(elapsedMs)}
          </span>
        )}
      </button>
      {expanded && (
        <div
          ref={scrollRef}
          aria-live="polite"
          className="px-[var(--chat-bubble-px)] py-[var(--chat-space-md)] chat-text-sm text-fg-secondary whitespace-pre-wrap overflow-y-auto border-t border-border-subtle"
          style={{
            maxHeight: inProgress ? '140px' : '360px',
            lineHeight: 'var(--chat-line-height)',
          }}
        >
          {text}
        </div>
      )}
    </div>
  );
};

const KnowledgeContextBlock: React.FC<{ sources: Extract<AssistantBlock, { type: 'knowledge_context' }>['sources'] }> = ({ sources }) => {
  const [expanded, setExpanded] = useState(false);
  const count = sources.length;

  return (
    <div className="my-[var(--chat-space-sm)] rounded-md border border-border bg-surface/60 overflow-hidden border-l-2 border-l-accent/70">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-1.5 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-sm text-fg-secondary hover:text-fg hover:bg-surface-hover transition-colors"
      >
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <BookOpen className="w-3.5 h-3.5 text-accent" />
        <span className="font-medium">Knowledge context</span>
        <span className="text-fg-muted ml-1 chat-text-xs">
          {count} source{count === 1 ? '' : 's'}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-border-subtle divide-y divide-border-subtle">
          {sources.map((source, index) => (
            <div key={`${source.source_path}-${index}`} className="px-[var(--chat-bubble-px)] py-[var(--chat-space-sm)]">
              <div className="flex items-center justify-between gap-2 chat-text-xs">
                <span className="text-accent truncate" title={source.source_path}>{source.source_path}</span>
                <span className="text-fg-muted shrink-0">{Math.round((source.score || 0) * 100)}%</span>
              </div>
              {source.preview && (
                <div className="mt-1 chat-text-xs text-fg-muted line-clamp-2 whitespace-pre-wrap">
                  {source.preview}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const ToolSummaryRow: React.FC<{
  summary: ToolSummary;
  expanded: boolean;
  onToggle: () => void;
}> = ({ summary, expanded, onToggle }) => {
  const bucketText = summary.toolBuckets.map((b) => `${b.label} ×${b.count}`).join(' · ');
  return (
    <button
      type="button"
      onClick={onToggle}
      className="w-full text-left rounded-md border border-border-subtle bg-surface/60 hover:bg-surface-hover transition-colors px-[var(--chat-bubble-px)] py-[var(--chat-space-sm)]"
    >
      <div className="flex items-center gap-2 chat-text-xs text-fg-secondary">
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span className="font-medium text-fg">Execution summary</span>
        <span className="text-fg-muted">
          {summary.total} calls · {summary.success} success
          {summary.error > 0 ? ` · ${summary.error} error` : ''}
          {summary.running > 0 ? ` · ${summary.running} running` : ''}
        </span>
      </div>
      {bucketText && <div className="mt-[var(--chat-space-xs)] chat-text-xs text-fg-muted truncate">{bucketText}</div>}
    </button>
  );
};

/**
 * In-stream plan question card — rendered inside the chat timeline.
 * Uses button-pill selection + a "Continue" confirmation step.
 */
const PlanQuestionsInlineCard: React.FC<{
  questions: PlanQuestion[];
  planState: PlanState;
  onUpdate: (questionId: string, selected: string[]) => void;
}> = ({ questions, planState, onUpdate }) => {
  const isInteractive = planState.phase === 'awaiting_decision';
  const [localSelections, setLocalSelections] = useState<Record<string, string[]>>(() => {
    const init: Record<string, string[]> = {};
    questions.forEach((q) => { init[q.id] = []; });
    return init;
  });
  const [confirmed, setConfirmed] = useState(false);

  const allAnswered = questions.every((q) => (localSelections[q.id] || []).length > 0);
  const showInteractive = isInteractive && !confirmed;

  const handleConfirm = () => {
    if (!allAnswered) return;
    questions.forEach((q) => onUpdate(q.id, localSelections[q.id] || []));
    setConfirmed(true);
  };

  const getAnsweredLabels = (q: PlanQuestion): string[] => {
    const ids = planState.decisions[q.id] || localSelections[q.id] || [];
    return ids.map((id) => q.options.find((o) => o.id === id)?.label || id);
  };

  return (
    <div className="my-2 rounded-xl border border-[color:var(--plan-pill-border)] overflow-hidden bg-[color-mix(in_srgb,var(--plan-pill-bg)_10%,var(--bg-surface))]">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[color:var(--plan-pill-border)]/40">
        <PlanModeIcon className="text-[color:var(--plan-pill-fg)] opacity-80 shrink-0" />
        <span className="chat-text-xs font-semibold text-[color:var(--plan-pill-fg)] uppercase tracking-wide">
          Planning — Decision Required
        </span>
        {!showInteractive && (
          <span className="ml-auto chat-text-xs text-fg-muted">Answered ✓</span>
        )}
      </div>

      {/* Questions */}
      <div className="px-4 py-3 space-y-4">
        {questions.map((q) => (
          <div key={q.id} className="space-y-2">
            <div className="chat-text-sm font-medium text-fg">{q.prompt}</div>
            {!showInteractive ? (
              <div className="flex flex-wrap gap-1.5">
                {getAnsweredLabels(q).map((label) => (
                  <span
                    key={label}
                    className="chat-text-xs px-2.5 py-1 rounded-md bg-accent/15 border border-accent/30 text-accent font-medium"
                  >
                    ✓ {label}
                  </span>
                ))}
                {getAnsweredLabels(q).length === 0 && (
                  <span className="chat-text-xs text-fg-muted italic">No selection recorded</span>
                )}
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {q.options.map((opt) => {
                  const isSelected = (localSelections[q.id] || []).includes(opt.id);
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => {
                        setLocalSelections((prev) => {
                          if (q.allow_multiple) {
                            const curr = prev[q.id] || [];
                            return {
                              ...prev,
                              [q.id]: curr.includes(opt.id)
                                ? curr.filter((id) => id !== opt.id)
                                : [...curr, opt.id],
                            };
                          }
                          return { ...prev, [q.id]: [opt.id] };
                        });
                      }}
                      className={`chat-text-sm px-3 py-1.5 rounded-lg border transition-all ${
                        isSelected
                          ? 'bg-accent/15 border-accent/60 text-accent font-medium shadow-sm'
                          : 'bg-surface border-border text-fg-secondary hover:border-accent/40 hover:text-fg hover:bg-surface-alt'
                      }`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ))}

        {showInteractive && (
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!allAnswered}
            className={`w-full py-2 px-4 rounded-lg font-medium chat-text-sm transition flex items-center justify-center gap-2 ${
              allAnswered
                ? 'bg-accent text-fg-on-accent hover:brightness-110 active:scale-[0.99]'
                : 'bg-surface-alt text-fg-muted border border-border cursor-not-allowed'
            }`}
          >
            Continue →
          </button>
        )}
      </div>
    </div>
  );
};

/**
 * In-stream plan draft review card — rendered inside the chat timeline.
 * Shows structured plan with collapsible sections and a prominent Build button.
 */
function buildPlanReviewMarkdown(
  block: Extract<AssistantBlock, { type: 'plan_draft' }>,
  planState: PlanState,
): string {
  const explicit = (block.draft || planState.draft || '').trim();
  if (explicit) return explicit;

  const sp = block.structured_plan || planState.structured_plan;
  const todos = planTasksForCard(block, planState);
  const lines: string[] = ['# Plan'];
  const goal = block.goal || planState.goal || sp?.goal || '';
  if (goal) lines.push('', '## Goal', goal);

  if (sp?.assumptions?.length) {
    lines.push('', '## Assumptions', ...sp.assumptions.map((item) => `- ${item}`));
  }

  if (todos.length > 0) {
    lines.push('', '## Tasks');
    todos.forEach((todo) => {
      lines.push(`- [ ] ${todo.title}`);
      if (todo.acceptance_criteria) lines.push(`  - Acceptance: ${todo.acceptance_criteria}`);
    });
  }

  if (sp?.risks?.length) {
    lines.push('', '## Risks', ...sp.risks.map((risk) => `- ${risk}`));
  }

  if (sp?.acceptance_criteria?.length) {
    lines.push('', '## Verification', ...sp.acceptance_criteria.map((item) => `- ${item}`));
  }

  return lines.join('\n').trim() || '# Plan\n\nPlan details are not available yet.';
}

function planTasksForCard(
  block: Extract<AssistantBlock, { type: 'plan_draft' }>,
  planState: PlanState,
): PlanTodo[] {
  const sp = block.structured_plan || planState.structured_plan || null;
  const primary =
    planState.todos.length > 0
      ? planState.todos
      : block.todos.length > 0
        ? block.todos
        : (sp?.todos || []);
  if (primary.length > 0) return primary;
  return (sp?.steps || []).map((step, index) => ({
    id: step.id || `step_${index + 1}`,
    title: step.title,
    status: 'pending' as const,
    depends_on: step.depends_on || [],
    parallel_group: step.parallel_group,
    acceptance_criteria: step.details || '',
  }));
}

const PlanDraftInlineCard: React.FC<{
  block: Extract<AssistantBlock, { type: 'plan_draft' }>;
  planState: PlanState;
  onBuild: () => void;
  onViewPlan?: () => void;
}> = ({ block, planState, onBuild, onViewPlan }) => {
  const canBuild = planState.phase === 'awaiting_approval' && !planState.approved;
  const sp = block.structured_plan || planState.structured_plan || null;
  const [open, setOpen] = useState<Record<string, boolean>>({ goal: false, tasks: true, files: false, risks: false, verification: false });
  const toggle = (k: string) => setOpen((prev) => ({ ...prev, [k]: !prev[k] }));

  const reviewPlanState =
    planState.phase === 'executing' || planState.phase === 'approved_waiting_build'
      ? { ...planState, todos: [] }
      : planState;
  const tasks: PlanTodo[] = planTasksForCard(block, reviewPlanState);
  const verification = sp?.acceptance_criteria || [];
  const context = sp?.context?.trim() || '';
  const criticalFiles = sp?.critical_files || [];

  return (
    <div className="my-2 rounded-xl border border-[color:var(--plan-pill-border)] overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-[color-mix(in_srgb,var(--plan-pill-bg)_18%,var(--bg-surface))] border-b border-[color:var(--plan-pill-border)]/40">
        <div className="flex items-center gap-2 mb-1">
          <PlanModeIcon className="text-[color:var(--plan-pill-fg)] opacity-80 shrink-0" />
          <span className="chat-text-xs font-semibold text-[color:var(--plan-pill-fg)] uppercase tracking-wide">
            Implementation Plan
          </span>
          {canBuild && (
            <span className="ml-auto chat-text-xs text-fg-muted">Ready to build</span>
          )}
        </div>
        <div className="chat-text-sm font-semibold text-fg leading-snug">{block.goal}</div>
      </div>

      {/* 任务目标 / Goal section */}
      {context && (
        <div className="border-b border-border-subtle">
          <button
            type="button"
            onClick={() => toggle('goal')}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-hover transition-colors text-left"
          >
            <span className="chat-text-xs font-medium text-fg-secondary uppercase tracking-wide">
              任务目标 / Goal
            </span>
            {open.goal
              ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted" />
              : <ChevronRight className="w-3.5 h-3.5 text-fg-muted" />}
          </button>
          {open.goal && (
            <div className="px-4 pb-3 chat-text-xs text-fg-secondary whitespace-pre-wrap leading-relaxed">
              {context}
            </div>
          )}
        </div>
      )}

      {/* 任务方案 / Approach (PART 1..N) */}
      {tasks.length > 0 && (
        <div className="border-b border-border-subtle">
          <button
            type="button"
            onClick={() => toggle('tasks')}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-hover transition-colors text-left"
          >
            <span className="chat-text-xs font-medium text-fg-secondary uppercase tracking-wide">
              任务方案 / Approach ({tasks.length})
            </span>
            {open.tasks
              ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted" />
              : <ChevronRight className="w-3.5 h-3.5 text-fg-muted" />}
          </button>
          {open.tasks && (
            <div className="px-4 pb-3 space-y-2">
              {tasks.map((t, i) => {
                const s = t.status || 'pending';
                return (
                  <div key={t.id} className="flex items-start gap-2.5 chat-text-xs">
                    <span className={`mt-0.5 w-4 h-4 rounded-full border flex-shrink-0 flex items-center justify-center text-[9px] font-bold ${
                      s === 'completed' ? 'bg-success/20 border-success/60 text-success' :
                      s === 'in_progress' ? 'bg-accent/20 border-accent text-accent' :
                      s === 'blocked' ? 'bg-danger/20 border-danger/60 text-danger' :
                      'bg-surface border-border text-fg-muted'
                    }`}>
                      {s === 'completed' ? '✓' : s === 'blocked' ? '!' : i + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <span className="text-fg-muted font-medium chat-text-xs uppercase tracking-wide mr-1">PART {i + 1}</span>
                      <span className={s === 'completed' ? 'line-through text-fg-muted' : 'text-fg'}>
                        {t.title}
                      </span>
                      {t.acceptance_criteria && (
                        <div className="mt-0.5 text-fg-muted text-[10px]">→ {t.acceptance_criteria}</div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 关键文件清单 / Critical Files section */}
      {criticalFiles.length > 0 && (
        <div className="border-b border-border-subtle">
          <button
            type="button"
            onClick={() => toggle('files')}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-hover transition-colors text-left"
          >
            <span className="chat-text-xs font-medium text-fg-secondary uppercase tracking-wide">
              关键文件清单 / Critical Files ({criticalFiles.length})
            </span>
            {open.files
              ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted" />
              : <ChevronRight className="w-3.5 h-3.5 text-fg-muted" />}
          </button>
          {open.files && (
            <div className="px-4 pb-3 space-y-1">
              {criticalFiles.map((cf, i) => (
                <div key={`${cf.path}-${i}`} className="chat-text-xs flex gap-1.5">
                  <code className="shrink-0 text-accent">{cf.path}</code>
                  {cf.change && <span className="text-fg-muted">— {cf.change}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Risks section */}
      {sp && sp.risks && sp.risks.length > 0 && (
        <div className="border-b border-border-subtle">
          <button
            type="button"
            onClick={() => toggle('risks')}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-hover transition-colors text-left"
          >
            <span className="chat-text-xs font-medium text-fg-secondary uppercase tracking-wide">
              Risks ({sp.risks.length})
            </span>
            {open.risks
              ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted" />
              : <ChevronRight className="w-3.5 h-3.5 text-fg-muted" />}
          </button>
          {open.risks && (
            <div className="px-4 pb-3 space-y-1">
              {sp.risks.map((r, i) => (
                <div key={i} className="chat-text-xs text-warning/80 flex gap-1.5">
                  <span className="shrink-0">⚠</span>
                  <span>{r}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Verification section */}
      {verification.length > 0 && (
        <div className="border-b border-border-subtle">
          <button
            type="button"
            onClick={() => toggle('verification')}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-hover transition-colors text-left"
          >
            <span className="chat-text-xs font-medium text-fg-secondary uppercase tracking-wide">
              验证 / Verification ({verification.length})
            </span>
            {open.verification
              ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted" />
              : <ChevronRight className="w-3.5 h-3.5 text-fg-muted" />}
          </button>
          {open.verification && (
            <div className="px-4 pb-3 space-y-1">
              {verification.map((item, i) => (
                <div key={i} className="chat-text-xs text-fg-secondary flex gap-1.5">
                  <Check className="mt-0.5 w-3 h-3 shrink-0 text-success" />
                  <span>{item}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {canBuild && (
        <div className="px-4 py-2.5 bg-[color-mix(in_srgb,var(--plan-pill-bg)_8%,var(--bg-surface))] flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={onViewPlan}
            className="chat-text-sm text-fg-secondary hover:text-fg"
          >
            View Plan
          </button>
          <button
            type="button"
            onClick={onBuild}
            className="py-1.5 px-3 rounded-md bg-[color:var(--plan-pill-bg)] text-[color:var(--plan-pill-fg)] font-semibold chat-text-sm hover:brightness-110 active:scale-[0.99] transition inline-flex items-center justify-center gap-1"
            title="Build plan (Ctrl+Enter)"
          >
            ▶ Build
          </button>
        </div>
      )}

    </div>
  );
};

type SyntaxHighlighterComponent = React.ComponentType<{
  language?: string;
  style?: unknown;
  customStyle?: React.CSSProperties;
  wrapLongLines?: boolean;
  children?: React.ReactNode;
}>;

let syntaxHighlighterPromise: Promise<{
  Component: SyntaxHighlighterComponent;
  styles: { oneLight: unknown; vscDarkPlus: unknown };
}> | null = null;

function loadSyntaxHighlighter() {
  if (!syntaxHighlighterPromise) {
    syntaxHighlighterPromise = Promise.all([
      import('react-syntax-highlighter'),
      import('react-syntax-highlighter/dist/esm/styles/prism'),
    ]).then(([highlighter, styles]) => ({
      Component: highlighter.Prism as SyntaxHighlighterComponent,
      styles: {
        oneLight: (styles as { oneLight: unknown }).oneLight,
        vscDarkPlus: (styles as { vscDarkPlus: unknown }).vscDarkPlus,
      },
    }));
  }
  return syntaxHighlighterPromise;
}

const LazyHighlightedCode: React.FC<{
  language: string;
  value: string;
  theme: 'dark' | 'light';
  customStyle: React.CSSProperties;
}> = ({ language, value, theme, customStyle }) => {
  const [loaded, setLoaded] = useState<Awaited<ReturnType<typeof loadSyntaxHighlighter>> | null>(null);

  useEffect(() => {
    let mounted = true;
    void loadSyntaxHighlighter().then((module) => {
      if (mounted) setLoaded(module);
    });
    return () => {
      mounted = false;
    };
  }, []);

  if (!loaded) {
    return (
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-b px-[var(--chat-space-lg)] py-[var(--chat-space-md)] font-mono chat-text-xs text-fg-secondary">
        {value}
      </pre>
    );
  }

  const Highlight = loaded.Component;
  return (
    <Highlight
      language={language || 'text'}
      style={theme === 'dark' ? loaded.styles.vscDarkPlus : loaded.styles.oneLight}
      customStyle={customStyle}
      wrapLongLines
    >
      {value}
    </Highlight>
  );
};

/** Code block with lightweight default rendering and optional highlighting. */
const CodeBlock: React.FC<{ language: string; value: string; theme: 'dark' | 'light' }> = ({ language, value, theme }) => {
  const [copied, setCopied] = useState(false);
  const [highlighted, setHighlighted] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  return (
    <div className="relative group my-[var(--chat-space-md)]">
      <div className="flex items-center justify-between px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] bg-surface-alt rounded-t-md border-b border-border-subtle">
        <span className="chat-text-xs text-fg-muted uppercase font-medium tracking-wide">{language || 'text'}</span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setHighlighted((value) => !value)}
            type="button"
            className="chat-text-xs text-fg-muted hover:text-fg-secondary transition-colors"
            aria-label={highlighted ? 'Disable syntax highlighting' : 'Enable syntax highlighting'}
          >
            {highlighted ? 'Plain' : 'Highlight'}
          </button>
          <button
            onClick={handleCopy}
            type="button"
            className="chat-text-xs text-fg-muted hover:text-fg-secondary transition-colors"
            aria-label="Copy code"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>
      {highlighted ? (
        <LazyHighlightedCode
          language={language}
          value={value}
          theme={theme}
          customStyle={{
            margin: 0,
            borderRadius: '0 0 0.25rem 0.25rem',
            fontSize: 'var(--chat-font-sm)',
            lineHeight: 'var(--chat-line-height)',
            padding: 'var(--chat-space-md) var(--chat-space-lg)',
          }}
        />
      ) : (
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-b px-[var(--chat-space-lg)] py-[var(--chat-space-md)] font-mono chat-text-xs text-fg-secondary">
          {value}
        </pre>
      )}
    </div>
  );
};

function trimCodePreview(value: string, maxLines = 20): string {
  const lines = value.split(/\r?\n/);
  if (lines.length <= maxLines) return value;
  return `${lines.slice(0, maxLines).join('\n')}\n...`;
}

const PlainCodeBlock: React.FC<{ language?: string; value: string }> = ({ language, value }) => (
  <div className="my-[var(--chat-space-sm)] overflow-hidden rounded-md border border-border-subtle bg-surface-alt">
    <div className="border-b border-border-subtle px-3 py-1 chat-text-xs font-medium uppercase text-fg-muted">
      {language || 'text'}
    </div>
    <pre className="max-h-72 overflow-auto whitespace-pre-wrap px-3 py-2 font-mono chat-text-xs text-fg-secondary">
      {trimCodePreview(value)}
    </pre>
  </div>
);

const timelineDotClass: Record<TimelineEvent['kind'], string> = {
  user: 'bg-accent',
  thinking: 'bg-info',
  text_summary: 'bg-fg-muted',
  tool: 'bg-success',
  file_edit: 'bg-success',
  todo: 'bg-accent',
  knowledge: 'bg-accent',
  image: 'bg-info',
  error: 'bg-danger',
  run_status: 'bg-fg-muted',
};

const TimelineEventShell = React.memo<{
  event: TimelineEvent;
  index: number;
  totalCount: number;
  children: React.ReactNode;
}>(({ event, index, totalCount, children }) => (
  <div className="px-[var(--chat-space-lg)] pb-[var(--chat-message-gap)] [contain:layout_paint]">
    <div className="relative pl-[var(--chat-timeline-indent)]">
      {index < totalCount - 1 && (
        <div className="absolute left-[5px] top-2.5 bottom-0 w-px bg-border-subtle" />
      )}
      <div className={`absolute left-[2px] top-2 w-1.5 h-1.5 rounded-full ${timelineDotClass[event.kind]}`} />
      {children}
    </div>
  </div>
));

TimelineEventShell.displayName = 'TimelineEventShell';

const TimelineThinkingRow = React.memo<{ event: Extract<TimelineEvent, { kind: 'thinking' }> }>(({ event }) => {
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const inProgress = !event.complete;

  useEffect(() => {
    if (!inProgress) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [inProgress]);

  const hasTimer = typeof event.startedAt === 'number';
  const elapsedMs = hasTimer
    ? (event.complete ? (event.endedAt ?? now) : now) - (event.startedAt as number)
    : 0;
  const label = inProgress ? 'Thinking' : hasTimer ? `Thought for ${formatThinkDuration(elapsedMs)}` : 'Thought';

  return (
    <div className="rounded-md border border-border-subtle bg-surface/50 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-xs text-fg-secondary hover:bg-surface-hover"
      >
        {inProgress ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-info shrink-0" />
        ) : expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-fg-muted shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-fg-muted shrink-0" />
        )}
        <span className="font-medium">{label}</span>
        {inProgress && hasTimer && (
          <span className="text-fg-muted tabular-nums">{formatThinkDuration(elapsedMs)}</span>
        )}
      </button>
      {expanded && (
        <div className="max-h-72 overflow-auto whitespace-pre-wrap border-t border-border-subtle px-[var(--chat-bubble-px)] py-[var(--chat-space-sm)] chat-text-sm text-fg-secondary">
          {event.text}
        </div>
      )}
    </div>
  );
});

TimelineThinkingRow.displayName = 'TimelineThinkingRow';

const TimelineToolGroupRow = React.memo<{
  event: TimelineToolEvent;
  mode: TimelineRenderMode;
  projectPath?: string | null;
}>(({ event, mode, projectPath }) => {
  const [expanded, setExpanded] = useState(false);
  const isPersonal = mode === 'personal';
  const Icon = event.status === 'running' ? Loader2 : event.status === 'error' ? AlertCircle : CheckCircle2;

  if (event.tools.length === 1 && !event.grouped && !event.disclosure) {
    const tool = event.tools[0];
    return (
      <ToolCallView
        name={tool.name}
        args={tool.args}
        result={tool.result}
        status={tool.status}
        durationMs={tool.durationMs}
        workerEvents={tool.workerEvents}
        variant={isPersonal ? 'disclosure' : 'event-row'}
        projectPath={projectPath}
      />
    );
  }

  return (
    <div
      className="my-[var(--chat-space-xs)] rounded-md border border-border-subtle bg-surface/45 overflow-hidden"
      data-testid={isPersonal ? 'personal-tool-disclosure' : 'coding-tool-group'}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex min-w-0 items-center gap-2 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-xs text-left hover:bg-surface-hover"
      >
        <Icon className={`w-3.5 h-3.5 shrink-0 ${event.status === 'running' ? 'animate-spin text-info' : event.status === 'error' ? 'text-danger' : 'text-success'}`} />
        {expanded ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-fg-muted shrink-0" />}
        <span className="font-medium text-fg-secondary truncate">{event.label}</span>
        <span className="ml-auto text-fg-muted shrink-0">
          {isPersonal ? 'details' : `${event.tools.length} calls`}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-border-subtle px-2 py-1.5">
          {event.tools.map((tool) => (
            <ToolCallView
              key={tool.id}
              name={tool.name}
              args={tool.args}
              result={tool.result}
              status={tool.status}
              durationMs={tool.durationMs}
              workerEvents={tool.workerEvents}
              variant={isPersonal ? 'disclosure' : 'event-row'}
              projectPath={projectPath}
            />
          ))}
        </div>
      )}
    </div>
  );
});

TimelineToolGroupRow.displayName = 'TimelineToolGroupRow';

const ChatImageThumbnail = React.memo<{
  image?: ImageAttachment;
  base64?: string;
  alt: string;
  ariaLabel: string;
  onOpen: (preview: ImagePreviewState) => void;
  buttonClassName?: string;
  imageClassName?: string;
}>(({
  image,
  base64,
  alt,
  ariaLabel,
  onOpen,
  buttonClassName = 'mb-[var(--chat-space-sm)]',
  imageClassName = 'max-w-full max-h-40',
}) => {
  const attachment = image || (base64 ? { base64, mimeType: 'image/png' } : null);
  if (!attachment) return null;
  const src = imageAttachmentSrc(attachment);
  if (!src) return null;
  const label = imageAttachmentLabel(attachment, alt);
  return (
    <button
      type="button"
      onClick={() => onOpen({ src, alt: label })}
      className={`group/image relative block max-w-full cursor-zoom-in rounded border border-border-subtle bg-surface/35 p-0 leading-none overflow-hidden focus:outline-none focus:ring-2 focus:ring-accent/60 ${buttonClassName}`}
      aria-label={ariaLabel}
      title={ariaLabel}
    >
      <img
        src={src}
        alt={label}
        loading="lazy"
        decoding="async"
        draggable={false}
        className={`${imageClassName} block rounded object-contain transition-transform duration-150 group-hover/image:scale-[1.01]`}
      />
      <span className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded bg-black/55 text-white opacity-0 transition-opacity group-hover/image:opacity-100 group-focus-visible/image:opacity-100">
        <Maximize2 className="h-3.5 w-3.5" />
      </span>
    </button>
  );
});

ChatImageThumbnail.displayName = 'ChatImageThumbnail';

const ImagePreviewOverlay = React.memo<{
  preview: ImagePreviewState | null;
  onClose: () => void;
}>(({ preview, onClose }) => {
  useEffect(() => {
    if (!preview) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [preview, onClose]);

  if (!preview) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Image preview"
      onClick={onClose}
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-full border border-white/20 bg-black/55 text-white hover:bg-black/70 focus:outline-none focus:ring-2 focus:ring-white/70"
        aria-label="Close image preview"
        title="Close image preview"
      >
        <X className="h-4 w-4" />
      </button>
      <div className="max-h-full max-w-full overflow-auto" onClick={(event) => event.stopPropagation()}>
        <img
          src={preview.src}
          alt={preview.alt}
          className="max-h-[92vh] max-w-[92vw] rounded-md object-contain shadow-2xl"
        />
      </div>
    </div>
  );
});

ImagePreviewOverlay.displayName = 'ImagePreviewOverlay';

interface ChatComposerProps {
  input: string;
  attachedImage: string | null;
  isRecording: boolean;
  recordingTime: number;
  isTranscribing: boolean;
  isRunning: boolean;
  planBlocksChatSend: boolean;
  showSlashMenu: boolean;
  slashQuery: string;
  showAtMenu: boolean;
  atQuery: string;
  mentionProjectOpen: boolean;
  fileTree: any[];
  sandboxMode: SandboxMode;
  chatMode: ClientChatMode;
  isPlanModeActive: boolean;
  thinkingIntensity: ThinkingIntensity;
  planState: PlanState;
  contextUsage?: ContextUsage | null;
  fileInputRef: React.RefObject<HTMLInputElement>;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onSubmitGuidance: () => void;
  onStop?: () => void;
  onFileSelect: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onKeyDown: (event: React.KeyboardEvent) => void;
  onPaste: (event: React.ClipboardEvent) => void;
  onCommand: (command: { name: string; args: string }) => void;
  onAtMention: (item: { id: string; label: string; category: string }) => void;
  onCloseSlash: () => void;
  onVisibleCommandsChange: (count: number) => void;
  onCloseAt: () => void;
  onRemoveImage: () => void;
  onOpenImage: (preview: ImagePreviewState) => void;
  onToggleSandboxMode: () => void;
  onChatModeChange: (mode: ClientChatMode) => void;
  onThinkingIntensityChange: (intensity: ThinkingIntensity) => void;
  onCompact?: () => void;
  formatTime: (seconds: number) => string;
}

const ChatComposer: React.FC<ChatComposerProps> = ({
  input,
  attachedImage,
  isRecording,
  recordingTime,
  isTranscribing,
  isRunning,
  planBlocksChatSend,
  showSlashMenu,
  slashQuery,
  showAtMenu,
  atQuery,
  mentionProjectOpen,
  fileTree,
  sandboxMode,
  chatMode,
  isPlanModeActive,
  thinkingIntensity,
  planState,
  contextUsage,
  fileInputRef,
  textareaRef,
  onInputChange,
  onSend,
  onSubmitGuidance,
  onStop,
  onFileSelect,
  onStartRecording,
  onStopRecording,
  onKeyDown,
  onPaste,
  onCommand,
  onAtMention,
  onCloseSlash,
  onVisibleCommandsChange,
  onCloseAt,
  onRemoveImage,
  onOpenImage,
  onToggleSandboxMode,
  onChatModeChange,
  onThinkingIntensityChange,
  onCompact,
  formatTime,
}) => (
  <>
    {attachedImage && (
      <div className="mb-2 flex items-center gap-2">
        <div className="relative inline-block">
          <ChatImageThumbnail
            base64={attachedImage}
            alt="preview"
            ariaLabel="Open attached image preview"
            onOpen={onOpenImage}
            buttonClassName=""
            imageClassName="h-16 max-w-[12rem]"
          />
          <button
            onClick={onRemoveImage}
            className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-danger rounded-full text-fg-on-danger flex items-center justify-center"
            aria-label="Remove image"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
        <span className="text-xs text-fg-muted">Image attached (will be sent to vision-capable models)</span>
      </div>
    )}

    <div className="flex items-center gap-2">
      <button
        onClick={() => fileInputRef.current?.click()}
        className="p-2 text-fg-muted hover:text-fg-secondary hover:bg-surface-hover rounded-lg transition-colors"
        title="Upload image"
        aria-label="Upload image"
      >
        <Image className="w-5 h-5" />
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={onFileSelect}
        aria-label="Select image to upload"
        title="Select image to upload"
      />

      {isRecording ? (
        <button
          onClick={onStopRecording}
          className="p-2 rounded-lg transition-colors bg-danger hover:bg-danger/85 text-fg-on-danger animate-pulse"
          title="Click to stop recording"
          aria-label="Stop recording"
        >
          <div className="flex items-center gap-1.5">
            <MicOff className="w-5 h-5" />
            <span className="text-xs font-mono">{formatTime(recordingTime)}</span>
          </div>
        </button>
      ) : (
        <button
          onClick={onStartRecording}
          disabled={isTranscribing || isRunning || planBlocksChatSend}
          className="p-2 text-fg-muted hover:text-fg-secondary hover:bg-surface-hover rounded-lg transition-colors disabled:opacity-50"
          title={planBlocksChatSend ? 'Voice input disabled while answering plan questions' : 'Voice input'}
          aria-label="Voice input"
        >
          {isTranscribing ? (
            <Loader2 className="w-5 h-5 animate-spin text-accent" />
          ) : (
            <Mic className="w-5 h-5" />
          )}
        </button>
      )}

      <div className="flex-1 relative">
        <textarea
          ref={textareaRef}
          value={input}
          disabled={isRecording || isTranscribing || planBlocksChatSend}
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          placeholder={
            planBlocksChatSend
              ? 'Complete the plan questions above to continue...'
              : isRecording
                ? 'Recording... Click mic to stop'
                : isTranscribing
                  ? 'Transcribing audio...'
                  : 'Type a message... (Shift+Enter for new line)'
          }
          rows={1}
          className="w-full min-h-[48px] bg-surface-input border border-border rounded-lg px-3 py-[11px] pr-11 text-[15px] leading-6 text-fg placeholder:text-fg-muted outline-none focus:border-accent resize-none max-h-[144px] disabled:opacity-60"
        />
        {showSlashMenu && (
          <SlashCommandMenu
            query={slashQuery}
            onSelect={onCommand}
            onClose={onCloseSlash}
            inputRef={textareaRef}
            onVisibleCommandsChange={onVisibleCommandsChange}
          />
        )}
        {showAtMenu && (
          <AtMentionMenu
            query={atQuery}
            onSelect={onAtMention}
            onClose={onCloseAt}
            inputRef={textareaRef}
            projectOpen={mentionProjectOpen}
            fileTree={fileTree}
          />
        )}
      </div>

      <button
        onClick={onToggleSandboxMode}
        disabled={isRunning}
        title={sandboxMode === 'sandbox' ? 'Sandbox mode - click for Unrestricted' : 'Unrestricted mode - click for Sandbox'}
        className={`p-2 rounded-lg transition-colors disabled:opacity-50 ${
          sandboxMode === 'sandbox'
            ? 'text-success hover:bg-surface-hover hover:text-success/85'
            : 'text-warning hover:bg-surface-hover hover:text-warning/85'
        }`}
      >
        {sandboxMode === 'sandbox' ? <Shield className="w-5 h-5" /> : <ShieldOff className="w-5 h-5" />}
      </button>

      <button
        onClick={onSend}
        disabled={planBlocksChatSend || (!input.trim() && !attachedImage)}
        aria-label={isRunning ? 'Queue task guidance' : 'Send'}
        title={
          planBlocksChatSend
            ? 'Send disabled until plan questions are answered'
            : isRunning
              ? '加入任务引导队列'
              : undefined
        }
        className="p-2 rounded-lg transition-colors bg-accent/85 hover:bg-accent text-fg-on-accent disabled:bg-surface-alt disabled:text-fg-muted"
      >
        <Send className="w-5 h-5" />
      </button>
      {isRunning && (
        <button
          type="button"
          onClick={onSubmitGuidance}
          disabled={planBlocksChatSend || (!input.trim() && !attachedImage)}
          aria-label="Submit task guidance now"
          title="立即提交引导（不中断当前任务）"
          className="p-2 rounded-lg border border-warning/35 bg-warning/10 text-warning transition-colors hover:bg-warning/20 disabled:border-border-subtle disabled:bg-surface-alt disabled:text-fg-muted"
        >
          <Zap className="w-5 h-5" />
        </button>
      )}
      {isRunning && (
        <button
          type="button"
          onClick={onStop}
          aria-label="Stop"
          title="Stop"
          className="p-2 rounded-lg transition-colors bg-danger hover:bg-danger/85 text-fg-on-danger"
        >
          <Square className="w-5 h-5" />
        </button>
      )}
    </div>

    <div
      className="mt-2 pt-2 border-t border-border-subtle flex items-center justify-between gap-3 flex-wrap"
      aria-label="Chat mode and thinking intensity"
    >
      <div className="flex items-center gap-2">
        <span className="chat-text-xs text-fg-muted">Mode</span>
        <button
          type="button"
          onClick={() => onChatModeChange('agent')}
          className={`chat-text-xs px-2.5 py-1 rounded-md border transition-colors ${
            chatMode === 'agent'
              ? 'bg-surface-alt border-border text-fg'
              : 'bg-surface border-border-subtle text-fg-muted hover:text-fg-secondary'
          }`}
        >
          Agent
        </button>
        <button
          type="button"
          onClick={() => onChatModeChange('plan')}
          aria-pressed={isPlanModeActive}
          aria-label="Plan mode"
          className={`chat-text-xs inline-flex items-center gap-1 pl-2 pr-1.5 py-1 rounded-full border transition-colors ${
            isPlanModeActive
              ? 'shadow-sm border-[color:var(--plan-pill-border)] bg-[color:var(--plan-pill-bg)] text-[color:var(--plan-pill-fg)]'
              : 'border-border-subtle text-fg-muted hover:text-fg-secondary bg-surface'
          }`}
        >
          <PlanModeIcon className="shrink-0 opacity-90" />
          <span className="font-medium pr-0.5">Plan</span>
          <ChevronDown className="w-3 h-3 shrink-0 opacity-60" aria-hidden />
        </button>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="chat-text-xs inline-flex h-7 items-center gap-1.5 rounded-md border border-border-subtle bg-surface px-2.5 text-fg-secondary transition-colors hover:border-border hover:bg-surface-hover hover:text-fg"
              aria-label={`Thinking intensity ${THINKING_LABELS[thinkingIntensity]}`}
            >
              <span className="text-fg-muted">Thinking</span>
              <span className="font-semibold text-info">{THINKING_LABELS[thinkingIntensity]}</span>
              <ChevronDown className="h-3 w-3 text-fg-muted" aria-hidden />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[128px]">
            {THINKING_LEVELS.map((level) => (
              <DropdownMenuItem
                key={level}
                onSelect={() => onThinkingIntensityChange(level)}
                className={`justify-between ${
                  thinkingIntensity === level ? 'text-info bg-info/10' : ''
                }`}
              >
                <span>{THINKING_LABELS[level]}</span>
                {thinkingIntensity === level && <Check className="h-3.5 w-3.5" aria-hidden />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <span className="chat-text-xs text-fg-muted ml-1" title="Server plan phase">
          Status: {planPhaseLabel(planState.phase)}
        </span>
        <ContextMeter
          usage={contextUsage}
          onCompact={onCompact}
          disabled={isRunning}
        />
      </div>
    </div>
  </>
);

export const ChatPanel: React.FC<ChatPanelProps> = ({
  sessionId,
  messages,
  toolCalls,
  fileEdits = [],
  runEvents = [],
  onSend,
  onStop,
  onRetry,
  isRunning,
  onDraftSave,
  onDraftLoad,
  onDraftClear,
  chatMode,
  onChatModeChange,
  thinkingIntensity,
  onThinkingIntensityChange,
  planState,
  collaborationState,
  onApprovePlan,
  onBuildPlan,
  onPauseBuild,
  onEndBuild,
  onPauseCollaboration,
  onCancelCollaboration,
  onAnswerCollaborationClarification,
  onRejectPlan,
  onUpdatePlanDecision,
  onSubmitPlanDecisions,
  onViewPlan,
  onCommand,
  contextUsage,
  checkpoints = [],
  taskGuidanceItems = [],
  onQueueTaskGuidance,
  onApplyTaskGuidance,
  onDeleteTaskGuidance,
  onClearTaskGuidance,
  onCompact,
  onClearSession,
  onLoadCheckpoints,
  onRewindToCheckpoint,
  rewindOpen = false,
  onRewindOpenChange,
  projectOpen = false,
  projectPath = null,
  fileTree = [],
  agentType = 'personal',
  projectName,
  assistantDisplayName,
}) => {
  const planBlocksChatSend = (chatMode === 'plan' || planState.mode === 'plan') && planState.phase === 'awaiting_decision';
  const isPlanModeActive = chatMode === 'plan';
  const mentionProjectOpen = agentType === 'coding' && projectOpen;
  const { resolved } = useTheme();
  const [input, setInput] = useState('');
  const [attachedImage, setAttachedImage] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<ImagePreviewState | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [sandboxMode, setSandboxMode] = useState<SandboxMode>(() => sandboxModeCache || 'sandbox');
  const [expandedToolDetails, setExpandedToolDetails] = useState<Record<string, boolean>>({});
  const [showAllToolDetails, setShowAllToolDetails] = useState<Record<string, boolean>>({});
  const [outputMode, setOutputMode] = useState<OutputMode>(getInitialOutputMode);
  const [hideToolNoise, setHideToolNoise] = useState<boolean>(getInitialNoiseFilter);
  const [personalChatV2Enabled] = useState(getPersonalChatV2Enabled);
  const [slashQuery, setSlashQuery] = useState('');
  const showSlashMenu = slashQuery !== '';
  const [slashVisibleCommandCount, setSlashVisibleCommandCount] = useState(0);
  const [atQuery, setAtQuery] = useState('');
  const showAtMenu = atQuery !== '';

  const density = outputMode === 'concise' ? 'compact' : outputMode === 'verbose' ? 'comfortable' : 'balanced';
  const usePersonalChatV2 = agentType === 'personal' && personalChatV2Enabled && chatMode !== 'plan';

  const openImagePreview = useCallback((preview: ImagePreviewState) => {
    setImagePreview(preview);
  }, []);

  const closeImagePreview = useCallback(() => {
    setImagePreview(null);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem('desktop-agent-output-mode', outputMode);
    } catch { /* ignore */ }
  }, [outputMode]);

  useEffect(() => {
    try {
      localStorage.setItem('desktop-agent-hide-tool-noise', hideToolNoise ? '1' : '0');
    } catch { /* ignore */ }
  }, [hideToolNoise]);

  // 加载当前权限模式
  useEffect(() => {
    let cancelled = false;
    const subscriber = (mode: SandboxMode) => {
      if (!cancelled) setSandboxMode(mode);
    };
    sandboxModeSubscribers.add(subscriber);
    if (sandboxModeCache) {
      setSandboxMode(sandboxModeCache);
    } else {
      void loadSandboxModeOnce().then((mode) => {
        if (mode && !cancelled) setSandboxMode(mode);
      });
    }
    return () => {
      cancelled = true;
      sandboxModeSubscribers.delete(subscriber);
    };
  }, []);

  const toggleSandboxMode = async () => {
    const next = sandboxMode === 'sandbox' ? 'unrestricted' : 'sandbox';
    if (next === 'unrestricted') {
      const ok = window.confirm('Unrestricted mode allows the agent to read/write files anywhere and execute any command (including dangerous ones).\n\nAre you sure you want to continue?');
      if (!ok) return;
    }
    try {
      await fetch(`${API_BASE}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sandbox_mode: next }),
      });
      await fetch(`${API_BASE}/api/config/reload`, { method: 'POST' });
      publishSandboxMode(next);
    } catch {
      // ignore
    }
  };

  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const messagesLengthRef = useRef(messages.length);
  const activeScrollSessionRef = useRef(sessionId);
  const initialScrollMemoryRef = useRef<ChatScrollMemory | undefined>(
    sessionId ? chatScrollMemoryBySession.get(sessionId) : undefined,
  );
  const scrollRestoreAppliedRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recordStreamRef = useRef<MediaStream | null>(null);

  // Release the recording timer and microphone stream if the component unmounts
  // mid-recording — otherwise the interval keeps firing setState on a dead
  // component and the audio track stays open.
  useEffect(() => () => {
    if (recordTimerRef.current) {
      clearInterval(recordTimerRef.current);
      recordTimerRef.current = null;
    }
    recordStreamRef.current?.getTracks().forEach((t) => t.stop());
    recordStreamRef.current = null;
  }, []);

  if (activeScrollSessionRef.current !== sessionId) {
    activeScrollSessionRef.current = sessionId;
    initialScrollMemoryRef.current = sessionId
      ? chatScrollMemoryBySession.get(sessionId)
      : undefined;
    scrollRestoreAppliedRef.current = false;
  }

  useEffect(() => {
    messagesLengthRef.current = messages.length;
  }, [messages.length]);

  const rememberScrollMemory = useCallback(
    (patch: Partial<ChatScrollMemory>) => {
      if (!sessionId) return;
      const existing = chatScrollMemoryBySession.get(sessionId);
      chatScrollMemoryBySession.set(sessionId, {
        ...existing,
        ...patch,
        messageCount: messagesLengthRef.current,
        updatedAt: Date.now(),
      });
      if (chatScrollMemoryBySession.size > 80) {
        const oldest = [...chatScrollMemoryBySession.entries()]
          .sort((a, b) => a[1].updatedAt - b[1].updatedAt)
          .slice(0, chatScrollMemoryBySession.size - 80);
        for (const [key] of oldest) chatScrollMemoryBySession.delete(key);
      }
    },
    [sessionId],
  );

  const saveVirtuosoSnapshot = useCallback(() => {
    if (!sessionId) return;
    virtuosoRef.current?.getState((snapshot) => {
      rememberScrollMemory({ snapshot });
    });
  }, [rememberScrollMemory, sessionId]);

  useEffect(() => {
    initialScrollMemoryRef.current = sessionId
      ? chatScrollMemoryBySession.get(sessionId)
      : undefined;
    scrollRestoreAppliedRef.current = false;
    return () => {
      saveVirtuosoSnapshot();
    };
  }, [saveVirtuosoSnapshot, sessionId]);

  // 加载草稿
  useEffect(() => {
    onDraftLoad?.().then((draft) => {
      if (draft) {
        setInput(draft);
        setTimeout(() => adjustTextareaHeight(), 0);
      }
    });
  }, [onDraftLoad]);

  // 自动保存草稿
  useEffect(() => {
    const timer = setTimeout(() => {
      onDraftSave?.(input);
    }, 1000);
    return () => clearTimeout(timer);
  }, [input, onDraftSave]);

  const adjustTextareaHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(Math.max(el.scrollHeight, CHAT_INPUT_MIN_HEIGHT), CHAT_INPUT_MAX_HEIGHT)}px`;
  };

  const scrollToBottom = useCallback(() => {
    virtuosoRef.current?.scrollToIndex({
      index: 'LAST',
      behavior: 'smooth',
      align: 'end',
    });
    setIsNearBottom(true);
    rememberScrollMemory({ atBottom: true });
  }, [rememberScrollMemory]);

  const handleRangeChanged = useCallback((range: ListRange) => {
    rememberScrollMemory({ range });
  }, [rememberScrollMemory]);

  const handleAtBottomStateChange = useCallback((atBottom: boolean) => {
    setIsNearBottom(atBottom);
    rememberScrollMemory({ atBottom });
  }, [rememberScrollMemory]);

  const resetComposer = () => {
    setInput('');
    setAttachedImage(null);
    onDraftClear?.();
    if (textareaRef.current) {
      textareaRef.current.style.height = `${CHAT_INPUT_MIN_HEIGHT}px`;
    }
  };

  const handleTaskGuidanceSend = (applyNow: boolean) => {
    if (planBlocksChatSend) return;
    if (!input.trim() && !attachedImage) return;
    onQueueTaskGuidance?.(input.trim(), attachedImage || undefined, { applyNow });
    resetComposer();
  };

  const handleSend = () => {
    if (planBlocksChatSend) return;
    if (!input.trim() && !attachedImage) return;
    if (isRunning) {
      handleTaskGuidanceSend(false);
      return;
    }
    const slashCommand = parseSlashInput(input);
    if (slashCommand && !attachedImage) {
      onCommand?.(slashCommand.command, slashCommand.args);
      setInput('');
      setSlashQuery('');
      setSlashVisibleCommandCount(0);
      onDraftClear?.();
      if (textareaRef.current) {
        textareaRef.current.style.height = `${CHAT_INPUT_MIN_HEIGHT}px`;
      }
      return;
    }
    onSend(input.trim(), attachedImage || undefined);
    setInput('');
    setAttachedImage(null);
    onDraftClear?.();
    if (textareaRef.current) {
      textareaRef.current.style.height = `${CHAT_INPUT_MIN_HEIGHT}px`;
    }
  };

  const handleSubmitGuidance = () => {
    if (!isRunning) {
      handleSend();
      return;
    }
    handleTaskGuidanceSend(true);
  };

  const handleAtMention = useCallback((item: { id: string; label: string; category: string }) => {
    setAtQuery('');
    // Replace the last @query with the structured mention
    const atIdx = input.lastIndexOf('@');
    const before = atIdx >= 0 ? input.slice(0, atIdx) : input;
    const mention = item.id; // e.g. "file:src/app/main.py" or "git" or "knowledge"
    const newInput = before + `@${mention} `;
    setInput(newInput);
    setTimeout(() => {
      textareaRef.current?.focus();
      adjustTextareaHeight();
    }, 0);
  }, [input]);

  const handleCommand = useCallback((cmd: { name: string; args: string }) => {
    setSlashQuery('');
    setSlashVisibleCommandCount(0);
    if (DIRECT_COMMANDS.has(cmd.name)) {
      setInput('');
      onDraftClear?.();
      if (textareaRef.current) {
        textareaRef.current.style.height = `${CHAT_INPUT_MIN_HEIGHT}px`;
      }
      onCommand?.(cmd.name, '');
    } else if (ARG_COMMANDS.has(cmd.name) || cmd.args) {
      // For commands with args, fill the command prefix and let user type args
      setInput(`/${cmd.name} `);
      setTimeout(() => textareaRef.current?.focus(), 0);
    } else {
      setInput(`/${cmd.name} `);
      setTimeout(() => textareaRef.current?.focus(), 0);
    }
  }, [onCommand, onDraftClear]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.defaultPrevented) return;
    if (e.key === 'Tab' && e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      onChatModeChange('plan');
      return;
    }
    if (showSlashMenu && e.key === 'Escape') {
      e.preventDefault();
      setSlashQuery('');
      setSlashVisibleCommandCount(0);
      return;
    }
    if (showSlashMenu && slashVisibleCommandCount > 0 && COMMAND_KEYS.has(e.key)) {
      e.preventDefault();
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      if (planBlocksChatSend) return;
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      const base64 = (ev.target?.result as string)?.split(',')[1];
      if (base64) setAttachedImage(base64);
    };
    reader.readAsDataURL(file);
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          const reader = new FileReader();
          reader.onload = (ev) => {
            const base64 = (ev.target?.result as string)?.split(',')[1];
            if (base64) setAttachedImage(base64);
          };
          reader.readAsDataURL(file);
        }
      }
    }
  };

  const handleInputChange = (val: string) => {
    setInput(val);
    adjustTextareaHeight();
    if (val.startsWith('/') && !val.includes(' ')) {
      setSlashQuery(val);
    } else {
      setSlashQuery('');
      setSlashVisibleCommandCount(0);
    }
    const atIdx = val.lastIndexOf('@');
    if (atIdx >= 0) {
      const afterAt = val.slice(atIdx);
      if (!afterAt.includes(' ') && afterAt.length <= 30) {
        setAtQuery(afterAt);
      } else {
        setAtQuery('');
      }
    } else {
      setAtQuery('');
    }
  };

  // ===== 语音录音 =====
  const formatTime = (sec: number) => {
    const m = Math.floor(sec / 60).toString().padStart(2, '0');
    const s = (sec % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  const startRecording = async () => {
    if (planBlocksChatSend) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recordStreamRef.current = stream;
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        stream.getTracks().forEach((t) => t.stop());
        recordStreamRef.current = null;
        transcribeAudio(blob);
      };

      mediaRecorder.onerror = () => {
        stream.getTracks().forEach((t) => t.stop());
        recordStreamRef.current = null;
        setIsRecording(false);
        if (recordTimerRef.current) {
          clearInterval(recordTimerRef.current);
          recordTimerRef.current = null;
        }
      };

      mediaRecorder.start(200);
      setIsRecording(true);
      setRecordingTime(0);
      recordTimerRef.current = setInterval(() => {
        setRecordingTime((t) => t + 1);
      }, 1000);
    } catch (e: any) {
      alert('Cannot access microphone: ' + (e.message || e));
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      if (recordTimerRef.current) {
        clearInterval(recordTimerRef.current);
        recordTimerRef.current = null;
      }
    }
  };

  const transcribeAudio = async (blob: Blob) => {
    setIsTranscribing(true);
    try {
      const formData = new FormData();
      formData.append('file', blob, 'recording.webm');
      const res = await fetch(`${API_BASE}/api/transcribe`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (data.text) {
        setInput((prev) => prev + (prev ? ' ' : '') + data.text);
        setTimeout(() => adjustTextareaHeight(), 0);
      } else if (data.error) {
        console.error('Transcription error:', data.error);
      }
    } catch (e) {
      console.error('Transcription failed:', e);
    } finally {
      setIsTranscribing(false);
    }
  };

  // 搜索过滤
  const filteredMessages = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return messages;
    return messages.filter((m) => m.content.toLowerCase().includes(q));
  }, [messages, searchQuery]);

  const timelineMode: TimelineRenderMode = agentType === 'coding' ? 'coding' : 'personal';
  const timelineEvents = useMemo(() => {
    if (usePersonalChatV2) return [];
    return buildTimelineEvents({
      messages: filteredMessages,
      toolCalls,
      fileEdits,
      runEvents,
      planState,
      mode: timelineMode,
    }).filter((event) => !(event.kind === 'todo' && event.source === 'execution'));
  }, [filteredMessages, toolCalls, fileEdits, runEvents, planState, timelineMode, usePersonalChatV2]);
  const collaborationRunEvents = useMemo(() => (
    collaborationEventsForRun(runEvents || [], collaborationState?.run_id || '')
  ), [runEvents, collaborationState?.run_id]);

  // Markdown 自定义渲染
  // react-markdown v9 中 fenced code blocks 由 pre 组件包裹，code 组件仅处理 inline code。
  const timelineItemCount = timelineEvents.length;
  const initialTopMostItemIndex = useMemo<IndexLocationWithAlign | number | undefined>(() => {
    const memory = initialScrollMemoryRef.current;
    if (timelineItemCount === 0) return undefined;
    if (!memory) {
      if (agentType === 'personal' && chatMode === 'plan') {
        return { index: 'LAST', align: 'end' };
      }
      return undefined;
    }
    if (memory.atBottom) return { index: 'LAST', align: 'end' };
    const index = Math.min(Math.max(memory.range?.startIndex ?? 0, 0), Math.max(timelineItemCount - 1, 0));
    return index > 0 ? { index, align: 'start' } : undefined;
  }, [agentType, chatMode, timelineItemCount, sessionId]);

  useEffect(() => {
    if (!sessionId || timelineItemCount === 0 || scrollRestoreAppliedRef.current) return;
    const memory = initialScrollMemoryRef.current || chatScrollMemoryBySession.get(sessionId);
    if (!memory) return;
    scrollRestoreAppliedRef.current = true;
    requestAnimationFrame(() => {
      if (memory.atBottom) {
        virtuosoRef.current?.scrollToIndex({ index: 'LAST', align: 'end', behavior: 'auto' });
        return;
      }
      const index = Math.min(Math.max(memory.range?.startIndex ?? 0, 0), Math.max(timelineItemCount - 1, 0));
      if (index > 0) {
        virtuosoRef.current?.scrollToIndex({ index, align: 'start', behavior: 'auto' });
      }
    });
  }, [timelineItemCount, sessionId]);

  const markdownComponents = useMemo(() => ({
    pre({ node, children, ...props }: any) {
      const codeNode = node?.children?.[0];
      if (codeNode?.tagName === 'code') {
        const className = codeNode.properties?.className?.[0] || '';
        const match = /language-(\w+)/.exec(className);
        const value = codeNode.children?.map((c: any) => c.value).join('') || '';
        return <CodeBlock language={match ? match[1] : ''} value={value} theme={resolved} />;
      }
      return <pre {...props}>{children}</pre>;
    },
    code({ node, className, children, ...props }: any) {
      const value = React.Children.toArray(children).map((child) => String(child)).join('');
      return (
        <RevealableInlineCode
          value={value}
          projectPath={projectPath}
          className="bg-surface-alt px-[var(--chat-space-xs)] py-[var(--chat-space-xs)] rounded chat-text-xs text-fg-secondary"
        >
          {children}
        </RevealableInlineCode>
      );
    },
  }), [resolved, projectPath]);

  const lightweightMarkdownComponents = useMemo(() => ({
    pre({ node, children, ...props }: any) {
      const codeNode = node?.children?.[0];
      if (codeNode?.tagName === 'code') {
        const className = codeNode.properties?.className?.[0] || '';
        const match = /language-(\w+)/.exec(className);
        const value = codeNode.children?.map((c: any) => c.value).join('') || '';
        return <PlainCodeBlock language={match ? match[1] : ''} value={value} />;
      }
      return <pre {...props}>{children}</pre>;
    },
    code({ children, ...props }: any) {
      const value = React.Children.toArray(children).map((child) => String(child)).join('');
      return (
        <RevealableInlineCode
          value={value}
          projectPath={projectPath}
          className="bg-surface-alt px-[var(--chat-space-xs)] py-[var(--chat-space-xs)] rounded chat-text-xs text-fg-secondary"
        >
          {children}
        </RevealableInlineCode>
      );
    },
  }), [projectPath]);

  const renderBlock = useCallback((block: AssistantBlock, _bi: number) => {
    switch (block.type) {
      case 'thinking':
        return (
          <ReasoningBlock
            key={`t-${block.timestamp}`}
            text={block.text}
            complete={block.complete}
            startedAt={block.startedAt}
            endedAt={block.endedAt}
          />
        );
      case 'text':
        return (
          <div key={`md-${block.timestamp}`} className="prose prose-sm chat-prose max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {block.text}
            </ReactMarkdown>
          </div>
        );
      case 'knowledge_context':
        return <KnowledgeContextBlock key={`kc-${block.timestamp}`} sources={block.sources} />;
      case 'tool_call':
        if (isInternalToolName(block.name)) return null;
        return (
          <ToolCallView
            key={`tc-${block.toolCallId || block.timestamp}`}
            name={block.name}
            args={block.args}
            result={block.result}
            status={block.status}
            durationMs={block.durationMs}
            workerEvents={block.workerEvents}
            projectPath={projectPath}
          />
        );
      case 'file_edit':
        return <FileEditView key={`edit-${block.edit.tool_call_id || block.timestamp}`} edit={block.edit} compact projectPath={projectPath} />;
      case 'image':
        return (
          <ChatImageThumbnail
            key={`img-${block.timestamp}`}
            image={imageAttachmentFromBlock(block) || undefined}
            alt="tool screenshot"
            ariaLabel="Open tool screenshot"
            onOpen={openImagePreview}
          />
        );
      case 'plan_questions':
        return null;
      case 'plan_answers':
        return null;
      case 'plan_execution':
        return null;
      case 'plan_draft':
        return (
          <PlanDraftInlineCard
            key={`pd-${block.timestamp}`}
            block={block}
            planState={planState}
            onBuild={onBuildPlan}
            onViewPlan={onViewPlan}
          />
        );
      default:
        return null;
    }
  }, [planState, onUpdatePlanDecision, onBuildPlan, onPauseBuild, onEndBuild, onViewPlan, markdownComponents, openImagePreview, projectPath]);

  const lastAssistantMsgId = useMemo(() => {
    const lastMsg = messages[messages.length - 1];
    return lastMsg?.role === 'assistant' && !lastMsg?.isTool ? lastMsg.id : null;
  }, [messages]);

  const renderTimelineEvent = useCallback((event: TimelineEvent, index: number) => {
    const markdownForMode = timelineMode === 'coding' ? lightweightMarkdownComponents : markdownComponents;
    const retryable =
      event.kind === 'text_summary' &&
      event.messageId === lastAssistantMsgId &&
      onRetry &&
      !isRunning;

    let content: React.ReactNode = null;

    switch (event.kind) {
      case 'user':
        content = (
          <div className={`relative group ${
            timelineMode === 'coding'
              ? 'rounded-md border border-accent/20 bg-accent/10 px-[var(--chat-bubble-px)] py-[var(--chat-bubble-py)] chat-text-sm text-fg'
              : 'bg-accent/15 text-fg rounded-lg px-[var(--chat-bubble-px)] py-[var(--chat-bubble-py)] ml-auto max-w-[85%] border border-accent/20 chat-text-sm'
          }`}>
            {event.imageBase64 && (
              <ChatImageThumbnail
                base64={event.imageBase64}
                alt="attached"
                ariaLabel="Open attached image"
                onOpen={openImagePreview}
              />
            )}
            <div className="prose prose-sm chat-prose chat-prose-plain max-w-none">
              <p className="whitespace-pre-wrap">{event.text}</p>
            </div>
          </div>
        );
        break;
      case 'thinking':
        content = <TimelineThinkingRow event={event} />;
        break;
      case 'text_summary':
        const streamingText = event.message?.turnComplete === false;
        content = (
          <div className="relative group py-[var(--chat-space-xs)] text-fg">
            {retryable && (
              <button
                type="button"
                onClick={onRetry}
                title="Regenerate"
                className="absolute -top-2 -right-2 w-5 h-5 bg-surface-alt hover:bg-surface-hover border border-border rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity z-10"
                aria-label="Regenerate"
              >
                <RotateCcw className="w-2.5 h-2.5 text-fg-secondary" />
              </button>
            )}
            {streamingText ? (
              <div className="chat-text-sm whitespace-pre-wrap leading-[var(--chat-line-height)] text-fg">
                {event.text}
              </div>
            ) : (
              <div className="prose prose-sm chat-prose max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownForMode}>
                  {event.text}
                </ReactMarkdown>
              </div>
            )}
          </div>
        );
        break;
      case 'tool':
        content = <TimelineToolGroupRow event={event} mode={timelineMode} projectPath={projectPath} />;
        break;
      case 'file_edit':
        content = <FileEditView edit={event.edit} compact variant="event-row" projectPath={projectPath} />;
        break;
      case 'knowledge':
        content = <KnowledgeContextBlock sources={event.sources} />;
        break;
      case 'image':
        content = (
          <ChatImageThumbnail
            image={event.image}
            alt="tool screenshot"
            ariaLabel="Open tool screenshot"
            onOpen={openImagePreview}
          />
        );
        break;
      case 'notice':
        content = (
          <div className="rounded-md border border-success/20 bg-success/10 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-xs text-success">
            {event.text}
          </div>
        );
        break;
      case 'todo':
        content = event.source === 'draft' && event.planDraft ? (
          <PlanDraftInlineCard
            block={event.planDraft}
            planState={planState}
            onBuild={onBuildPlan}
            onViewPlan={onViewPlan}
          />
        ) : (
          <PlanExecutionCard
            goal={event.goal || planState.goal}
            todos={event.todos}
            phase={event.phase || planState.phase}
            compact
            onPause={onPauseBuild}
            onEnd={onEndBuild}
            onContinue={onBuildPlan}
          />
        );
        break;
      case 'error':
        content = (
          <div className="rounded-md border border-danger/20 bg-danger/10 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-xs text-danger">
            {event.text}
          </div>
        );
        break;
      case 'run_status':
        content = (
          <div className="rounded-md border border-border-subtle bg-surface/35 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-xs text-fg-secondary">
            <span className="font-medium text-fg">{event.label}</span>
            {event.detail && <span className="text-fg-muted"> - {event.detail}</span>}
          </div>
        );
        break;
      default:
        content = null;
    }

    return (
      <TimelineEventShell
        key={event.id}
        event={event}
        index={index}
        totalCount={timelineEvents.length}
      >
        {content}
      </TimelineEventShell>
    );
  }, [
    timelineMode,
    lightweightMarkdownComponents,
    markdownComponents,
    lastAssistantMsgId,
    onRetry,
    isRunning,
    timelineEvents.length,
    planState,
    onBuildPlan,
    onViewPlan,
    onPauseBuild,
    onEndBuild,
    openImagePreview,
    projectPath,
  ]);

  const itemContent = useCallback((index: number) => {
    const event = timelineEvents[index];
    if (!event) return null;
    return renderTimelineEvent(event, index);
  }, [timelineEvents, renderTimelineEvent]);

  const virtuosoInitialProps = useMemo(
    () => initialTopMostItemIndex === undefined ? {} : { initialTopMostItemIndex },
    [initialTopMostItemIndex],
  );

  const planTaskRequirement =
    chatMode === 'plan'
      ? (planState.goal || planState.draft.split('\n')[0]?.replace(/^Goal:\s*/, '') || '')
      : '';

  const virtuosoComponents: any = useMemo(() => ({
    Header: () => (
      <>
        <div className="h-[var(--chat-space-md)]" />
        {planTaskRequirement && (
          <div className="px-[var(--chat-space-lg)] pb-[var(--chat-space-sm)]">
            <div className="rounded-md border border-accent/30 bg-surface/95 backdrop-blur px-3 py-2">
              <div className="chat-text-xs text-fg-secondary">
                <span className="text-fg font-medium">Task requirement:</span>{' '}
                {planTaskRequirement}
              </div>
            </div>
          </div>
        )}
      </>
    ),
    Footer: isRunning
      ? () => (
          <div className="px-[var(--chat-space-lg)] pb-[var(--chat-message-gap)]">
            <div className="relative pl-[var(--chat-timeline-indent)] py-[var(--chat-space-xs)]">
              <div className="absolute left-[5px] top-0 bottom-0 w-px bg-border-subtle" />
              <div className="absolute left-[2px] top-1.5 w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
              <AgentRunningStatus
                label="Agent is working..."
                className="pl-1 chat-text-xs text-fg-muted"
                iconClassName="w-3 h-3 text-accent"
              />
            </div>
          </div>
        )
      : undefined,
    EmptyPlaceholder: messages.length === 0
      ? () => (
          <EmptyChatWelcome
            agentType={agentType}
            chatMode={chatMode}
            projectName={projectName}
            assistantDisplayName={assistantDisplayName}
          />
        )
      : null,
  }), [agentType, assistantDisplayName, chatMode, isRunning, messages.length, planTaskRequirement, projectName]);

  return (
    <div className="relative h-full min-h-0 flex flex-col overflow-hidden bg-app" data-density={density}>
      <ImagePreviewOverlay preview={imagePreview} onClose={closeImagePreview} />
      {/* 搜索栏 */}
      {showSearch && (
        <div className="px-4 pt-3 pb-1 border-b border-border flex items-center gap-2">
          <Search className="w-4 h-4 text-fg-muted shrink-0" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search messages..."
            className="flex-1 bg-surface-input border border-border rounded px-2 py-1 text-xs text-fg placeholder:text-fg-muted outline-none focus:border-accent"
            autoFocus
            data-search-input
          />
          <button
            onClick={() => { setShowSearch(false); setSearchQuery(''); }}
            className="text-xs text-fg-muted hover:text-fg-secondary"
            aria-label="Close search"
          >
            Esc
          </button>
        </div>
      )}

      {/* 输出风格控制 */}
      {!usePersonalChatV2 && (
      <div className="px-[var(--chat-space-lg)] pt-[var(--chat-space-md)] pb-[var(--chat-space-sm)] border-b border-border-subtle flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5">
          {(['concise', 'balanced', 'verbose'] as OutputMode[]).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setOutputMode(mode)}
              className={`chat-text-xs px-2 py-0.5 rounded border transition-colors ${
                outputMode === mode
                  ? 'bg-surface-alt border-border text-fg'
                  : 'bg-surface border-border-subtle text-fg-muted hover:text-fg-secondary'
              }`}
            >
              {mode === 'concise' ? 'Concise' : mode === 'balanced' ? 'Balanced' : 'Verbose'}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setHideToolNoise((v) => !v)}
          className={`chat-text-xs px-2 py-0.5 rounded border transition-colors ${
            hideToolNoise
              ? 'bg-info/10 border-info/30 text-info'
              : 'bg-surface border-border-subtle text-fg-muted hover:text-fg-secondary'
          }`}
        >
          {hideToolNoise ? 'Noise filter: ON' : 'Noise filter: OFF'}
        </button>
      </div>
      )}

      {/* 消息列表 */}
      <div
        className="min-h-0 flex-1 relative overflow-hidden"
        data-testid={usePersonalChatV2 ? 'personal-chat-v2-container' : timelineMode === 'coding' ? 'coding-event-timeline' : 'personal-conversation-timeline'}
      >
        {usePersonalChatV2 ? (
          <PersonalChatSurface
            sessionId={sessionId}
            messages={messages}
            toolCalls={toolCalls}
            fileEdits={fileEdits}
            planState={planState}
            searchQuery={searchQuery}
            isRunning={isRunning}
            onRetry={onRetry}
            onOpenImage={openImagePreview}
            markdownTheme={resolved}
            assistantDisplayName={assistantDisplayName}
            projectPath={projectPath}
            emptyPlaceholder={(
              <EmptyChatWelcome
                agentType={agentType}
                chatMode={chatMode}
                projectName={projectName}
                assistantDisplayName={assistantDisplayName}
              />
            )}
          />
        ) : (
          <Virtuoso
            ref={virtuosoRef}
            className="h-full"
            data={timelineEvents}
            {...virtuosoInitialProps}
            followOutput={isNearBottom ? 'smooth' : false}
            atBottomStateChange={handleAtBottomStateChange}
            rangeChanged={handleRangeChanged}
            overscan={200}
            computeItemKey={(_index, event) => event.id}
            itemContent={itemContent}
            components={virtuosoComponents}
          />
        )}
      </div>

      {/* Scroll to bottom button */}
      {!usePersonalChatV2 && !isNearBottom && messages.length > 0 && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-20 left-1/2 -translate-x-1/2 bg-surface-alt hover:bg-surface-hover text-fg chat-text-xs px-[var(--chat-space-lg)] py-[var(--chat-space-sm)] rounded-full border border-border flex items-center gap-1 shadow-lg transition-colors z-10"
          aria-label="Scroll to bottom"
        >
          <ArrowDown className="w-3 h-3" />
          Scroll to bottom
        </button>
      )}

      {/* Input area */}
      <div className="relative z-30 shrink-0 border-t border-border p-[var(--chat-space-lg)] bg-surface">
        {planState.phase === 'awaiting_decision' && planState.questions.length > 0 && (
          <PlanQuestionsDock
            questions={planState.questions}
            onSubmit={onSubmitPlanDecisions}
          />
        )}
        {planState.phase === 'planning' && (
          <div className="mb-3">
            <CreatingPlanStatus />
          </div>
        )}
        {(planState.phase === 'executing' || planState.phase === 'approved_waiting_build') && planState.todos.length > 0 && (
          <div className="mb-2">
            <PlanExecutionCard
              goal={planState.goal}
              todos={planState.todos}
              phase={planState.phase}
              onPause={onPauseBuild}
              onEnd={onEndBuild}
              onContinue={onBuildPlan}
            />
          </div>
        )}
        {collaborationState?.active && (
          <div className="mb-2">
            <CollaborationTrack
              recaps={collaborationState.recap ? [collaborationState.recap] : []}
              teamProgress={collaborationState.teamProgress}
              evidence={collaborationState.evidence || []}
              artifacts={collaborationState.artifacts || []}
              events={collaborationRunEvents}
              status={collaborationState.status || collaborationState.currentPhase || ''}
              pendingClarification={collaborationState.pendingClarification || null}
              onPause={onPauseCollaboration}
              onCancel={onCancelCollaboration}
              onAnswerClarification={onAnswerCollaborationClarification}
            />
          </div>
        )}
        {/* ── Plan mode status bar ── */}
        {chatMode === 'plan' && (
          <div
            className="mb-2 rounded-lg border px-3 py-1.5 chat-text-xs border-[color-mix(in_srgb,var(--plan-pill-border)_55%,transparent)] bg-[color-mix(in_srgb,var(--plan-pill-bg)_12%,var(--bg-surface))]"
            role="status"
          >
            <div className="flex items-center gap-2 text-fg flex-wrap">
              <PlanModeIcon className="shrink-0 opacity-70" />
              <span className="font-medium">Plan mode</span>
              {planState.phase !== 'idle' && (
                <>
                  <span className="text-fg-muted">·</span>
                  <span className="text-fg-secondary">{planPhaseLabel(planState.phase)}</span>
                </>
              )}
              {planState.goal && planState.phase !== 'idle' && (
                <>
                  <span className="text-fg-muted">·</span>
                  <span className="text-fg-muted truncate max-w-[240px]">{planState.goal.slice(0, 72)}</span>
                </>
              )}
              {/* Open plan file link */}
              {planState.plan_file_path && (
                <button
                  type="button"
                  className="ml-auto chat-text-xs text-fg-muted hover:text-fg-secondary underline underline-offset-2 shrink-0"
                  onClick={() => {
                    if (onViewPlan) {
                      onViewPlan();
                    } else if (typeof window !== 'undefined' && (window as any).electronAPI?.openPath) {
                      (window as any).electronAPI.openPath(planState.plan_file_path);
                    }
                  }}
                  title="Open plan file in editor"
                >
                  Open plan file
                </button>
              )}
            </div>
          </div>
        )}
        <TaskGuidanceQueueCard
          items={taskGuidanceItems}
          isRunning={isRunning}
          onApply={onApplyTaskGuidance}
          onDelete={onDeleteTaskGuidance}
          onClear={onClearTaskGuidance}
        />
        <ChatComposer
          input={input}
          attachedImage={attachedImage}
          isRecording={isRecording}
          recordingTime={recordingTime}
          isTranscribing={isTranscribing}
          isRunning={isRunning}
          planBlocksChatSend={planBlocksChatSend}
          showSlashMenu={showSlashMenu}
          slashQuery={slashQuery}
          showAtMenu={showAtMenu}
          atQuery={atQuery}
          mentionProjectOpen={mentionProjectOpen}
          fileTree={fileTree}
          sandboxMode={sandboxMode}
          chatMode={chatMode}
          isPlanModeActive={isPlanModeActive}
          thinkingIntensity={thinkingIntensity}
          planState={planState}
          contextUsage={contextUsage}
          fileInputRef={fileInputRef}
          textareaRef={textareaRef}
          onInputChange={handleInputChange}
          onSend={handleSend}
          onSubmitGuidance={handleSubmitGuidance}
          onStop={onStop}
          onFileSelect={handleFileSelect}
          onStartRecording={startRecording}
          onStopRecording={stopRecording}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onCommand={handleCommand}
          onAtMention={handleAtMention}
          onCloseSlash={() => {
            setSlashQuery('');
            setSlashVisibleCommandCount(0);
          }}
          onVisibleCommandsChange={setSlashVisibleCommandCount}
          onCloseAt={() => setAtQuery('')}
          onRemoveImage={() => setAttachedImage(null)}
          onOpenImage={openImagePreview}
          onToggleSandboxMode={toggleSandboxMode}
          onChatModeChange={onChatModeChange}
          onThinkingIntensityChange={onThinkingIntensityChange}
          onCompact={() => onCompact?.(false)}
          formatTime={formatTime}
        />
      </div>
      <RewindModal
        open={rewindOpen}
        checkpoints={checkpoints}
        onClose={() => onRewindOpenChange?.(false)}
        onLoad={onLoadCheckpoints || (async () => [])}
        onRewind={onRewindToCheckpoint || (() => {})}
        isRunning={isRunning}
      />
    </div>
  );
};
