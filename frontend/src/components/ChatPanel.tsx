import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Send, Image, Loader2, Square, ChevronDown, ChevronRight, RotateCcw, Mic, MicOff, Search, ArrowDown, Shield, ShieldOff, BookOpen, Check, Circle, CheckCircle2, AlertCircle, Bot, Code2, FolderOpen, Pause, Play, X } from 'lucide-react';
import { Virtuoso, VirtuosoHandle } from 'react-virtuoso';
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
  ContextUsage,
  ConversationCheckpoint,
  TaskGuidanceItem,
} from '../types';
import { API_BASE } from '../config';
import { useTheme } from '../hooks/useTheme';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight, vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { ToolCallView } from './ToolCallView';
import { FileEditView } from './FileEditView';
import { SlashCommandMenu } from './SlashCommandMenu';
import { AtMentionMenu } from './AtMentionMenu';
import { ChatMessageItem } from './ChatMessageItem';
import { ContextMeter } from './ContextMeter';
import { RewindModal } from './RewindModal';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './ui/DropdownMenu';

interface ChatPanelProps {
  messages: ChatMessage[];
  toolCalls: ToolCall[];
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
  onApprovePlan: () => void;
  onBuildPlan: () => void;
  onPauseBuild: () => void;
  onEndBuild: () => void;
  onRejectPlan: () => void;
  onUpdatePlanDecision: (questionId: string, selected: string[]) => void;
  onSubmitPlanDecisions: (answers: PlanDecisionAnswer[]) => void;
  onViewPlan?: () => void;
  onCommand?: (command: string, args: string) => void;
  contextUsage?: ContextUsage | null;
  checkpoints?: ConversationCheckpoint[];
  taskGuidanceItems?: TaskGuidanceItem[];
  onQueueTaskGuidance?: (text: string, imageBase64?: string) => void;
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
  fileTree?: any[];
  agentType?: AgentType;
  projectName?: string;
}

type OutputMode = 'concise' | 'balanced' | 'verbose';

const COMMAND_KEYS = new Set(['ArrowDown', 'ArrowUp', 'Enter', 'Escape']);
const DIRECT_COMMANDS = new Set([
  'clear',
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

function isNoisyToolBlock(block: Extract<AssistantBlock, { type: 'tool_call' }>): boolean {
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
}> = ({ agentType, chatMode, projectName }) => {
  const { t } = useTranslation();
  const isCoding = agentType === 'coding';
  const AgentIcon = isCoding ? Code2 : Bot;
  const agentLabel = isCoding ? t('chat.empty.codingAgent') : t('chat.empty.personalAgent');
  const modeLabel = chatMode === 'plan' ? t('chat.empty.planMode') : t('chat.empty.agentMode');
  const title = projectName
    ? t('chat.empty.projectReady', { projectName })
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
          <EmptyStatusChip tone={chatMode === 'plan' ? 'accent' : 'neutral'}>{modeLabel}</EmptyStatusChip>
          {projectName && (
            <EmptyStatusChip title={projectName}>
              <span className="inline-flex min-w-0 items-center gap-1.5">
                <FolderOpen className="h-3 w-3 shrink-0" />
                <span className="truncate">{projectName}</span>
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
  const visible = items.filter((item) => item.status !== 'consumed');
  if (visible.length === 0) return null;

  const actionableCount = visible.filter((item) => item.status === 'queued' || item.status === 'stale').length;
  const waitingCount = visible.filter((item) => item.status === 'applied').length;

  return (
    <div className="mb-2 rounded-md border border-accent/25 bg-accent/5 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="chat-text-xs font-semibold text-fg">任务引导队列 ({visible.length})</div>
          <div className="chat-text-xs text-fg-muted">
            {waitingCount > 0 ? `等待 Agent 读取 ${waitingCount} 条` : `${actionableCount} 条待引导`}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onApply}
            disabled={!isRunning || actionableCount === 0}
            className="chat-text-xs rounded-md bg-accent/85 px-2.5 py-1 font-medium text-fg-on-accent hover:bg-accent disabled:bg-surface-alt disabled:text-fg-muted"
          >
            任务引导
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
              ? '等待读取'
              : item.status === 'stale'
                ? '未读取'
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
  const [expanded, setExpanded] = useState(false);
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
          className="px-[var(--chat-bubble-px)] py-[var(--chat-space-md)] font-mono chat-text-xs text-fg-secondary whitespace-pre-wrap overflow-y-auto border-t border-border-subtle"
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
  const isExecuting = planState.phase === 'executing';
  const canBuild = planState.phase === 'awaiting_approval' && !planState.approved;
  const sp = block.structured_plan || planState.structured_plan || null;
  const [open, setOpen] = useState<Record<string, boolean>>({ goal: false, tasks: true, files: false, risks: false, verification: false });
  const toggle = (k: string) => setOpen((prev) => ({ ...prev, [k]: !prev[k] }));

  // Use live todos from planState when executing for real-time status
  const tasks: PlanTodo[] = isExecuting && planState.todos.length > 0
    ? planState.todos
    : planTasksForCard(block, planState);
  const verification = sp?.acceptance_criteria || [];
  const context = sp?.context?.trim() || '';
  const criticalFiles = sp?.critical_files || [];
  // Defensive: only show the live "Building" pulse while a todo is actually
  // in progress. If the backend's terminal transition is delayed, this stops
  // the indicator from spinning forever once every todo is resolved.
  const allTasksResolved = tasks.length > 0 && tasks.every((t) => t.status === 'completed' || t.status === 'cancelled');
  const showBuilding = isExecuting && !allTasksResolved;

  return (
    <div className="my-2 rounded-xl border border-[color:var(--plan-pill-border)] overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-[color-mix(in_srgb,var(--plan-pill-bg)_18%,var(--bg-surface))] border-b border-[color:var(--plan-pill-border)]/40">
        <div className="flex items-center gap-2 mb-1">
          <PlanModeIcon className="text-[color:var(--plan-pill-fg)] opacity-80 shrink-0" />
          <span className="chat-text-xs font-semibold text-[color:var(--plan-pill-fg)] uppercase tracking-wide">
            Implementation Plan
          </span>
          {showBuilding && (
            <span className="ml-auto flex items-center gap-1.5 chat-text-xs text-accent">
              <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse inline-block" />
              Building
            </span>
          )}
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

      {isExecuting && (
        <div className="px-4 py-2.5 flex items-center gap-2 chat-text-xs text-accent bg-[color-mix(in_srgb,var(--plan-pill-bg)_8%,var(--bg-surface))]">
          <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse inline-block" />
          Plan approved — executing…
        </div>
      )}
    </div>
  );
};

/** Code block with syntax highlighting and copy button */
const CodeBlock: React.FC<{ language: string; value: string; theme: 'dark' | 'light' }> = ({ language, value, theme }) => {
  const [copied, setCopied] = useState(false);

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
        <button
          onClick={handleCopy}
          type="button"
          className="chat-text-xs text-fg-muted hover:text-fg-secondary transition-colors"
          aria-label="Copy code"
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <SyntaxHighlighter
        language={language || 'text'}
        style={theme === 'dark' ? vscDarkPlus : oneLight}
        customStyle={{
          margin: 0,
          borderRadius: '0 0 0.25rem 0.25rem',
          fontSize: 'var(--chat-font-sm)',
          lineHeight: 'var(--chat-line-height)',
          padding: 'var(--chat-space-md) var(--chat-space-lg)',
        }}
        wrapLongLines
      >
        {value}
      </SyntaxHighlighter>
    </div>
  );
};

export const ChatPanel: React.FC<ChatPanelProps> = ({
  messages,
  toolCalls,
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
  onApprovePlan,
  onBuildPlan,
  onPauseBuild,
  onEndBuild,
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
  fileTree = [],
  agentType = 'personal',
  projectName,
}) => {
  const planBlocksChatSend = (chatMode === 'plan' || planState.mode === 'plan') && planState.phase === 'awaiting_decision';
  const isPlanModeActive = chatMode === 'plan';
  const { resolved } = useTheme();
  const [input, setInput] = useState('');
  const [attachedImage, setAttachedImage] = useState<string | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [sandboxMode, setSandboxMode] = useState<'sandbox' | 'unrestricted'>('sandbox');
  const [expandedToolDetails, setExpandedToolDetails] = useState<Record<string, boolean>>({});
  const [showAllToolDetails, setShowAllToolDetails] = useState<Record<string, boolean>>({});
  const [outputMode, setOutputMode] = useState<OutputMode>(getInitialOutputMode);
  const [hideToolNoise, setHideToolNoise] = useState<boolean>(getInitialNoiseFilter);
  const [slashQuery, setSlashQuery] = useState('');
  const showSlashMenu = slashQuery !== '';
  const [atQuery, setAtQuery] = useState('');
  const showAtMenu = atQuery !== '';

  const density = outputMode === 'concise' ? 'compact' : outputMode === 'verbose' ? 'comfortable' : 'balanced';

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
    fetch(`${API_BASE}/api/settings`)
      .then((res) => res.json())
      .then((data) => {
        const mode = data.settings?.sandbox_mode;
        if (mode === 'sandbox' || mode === 'unrestricted') {
          setSandboxMode(mode);
        }
      })
      .catch(() => {});
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
      setSandboxMode(next);
    } catch {
      // ignore
    }
  };

  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  };

  const scrollToBottom = useCallback(() => {
    virtuosoRef.current?.scrollToIndex({
      index: 'LAST',
      behavior: 'smooth',
      align: 'end',
    });
    setIsNearBottom(true);
  }, []);

  const handleSend = () => {
    if (planBlocksChatSend) return;
    if (!input.trim() && !attachedImage) return;
    if (isRunning) {
      onQueueTaskGuidance?.(input.trim(), attachedImage || undefined);
      setInput('');
      setAttachedImage(null);
      onDraftClear?.();
      if (textareaRef.current) {
        textareaRef.current.style.height = '40px';
      }
      return;
    }
    const slashCommand = parseSlashInput(input);
    if (slashCommand && !attachedImage) {
      onCommand?.(slashCommand.command, slashCommand.args);
      setInput('');
      setSlashQuery('');
      onDraftClear?.();
      if (textareaRef.current) {
        textareaRef.current.style.height = '40px';
      }
      return;
    }
    onSend(input.trim(), attachedImage || undefined);
    setInput('');
    setAttachedImage(null);
    onDraftClear?.();
    if (textareaRef.current) {
      textareaRef.current.style.height = '40px';
    }
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
    if (DIRECT_COMMANDS.has(cmd.name)) {
      onCommand?.(cmd.name, '');
      setInput('');
    } else if (ARG_COMMANDS.has(cmd.name) || cmd.args) {
      // For commands with args, fill the command prefix and let user type args
      setInput(`/${cmd.name} `);
      setTimeout(() => textareaRef.current?.focus(), 0);
    } else {
      setInput(`/${cmd.name} `);
      setTimeout(() => textareaRef.current?.focus(), 0);
    }
  }, [onCommand]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.defaultPrevented) return;
    if (e.key === 'Tab' && e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      onChatModeChange('plan');
      return;
    }
    if (showSlashMenu && COMMAND_KEYS.has(e.key)) {
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
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        stream.getTracks().forEach((t) => t.stop());
        transcribeAudio(blob);
      };

      mediaRecorder.onerror = () => {
        stream.getTracks().forEach((t) => t.stop());
        setIsRecording(false);
        if (recordTimerRef.current) clearInterval(recordTimerRef.current);
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

  // Markdown 自定义渲染
  // react-markdown v9 中 fenced code blocks 由 pre 组件包裹，code 组件仅处理 inline code。
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
      return (
        <code className="bg-surface-alt px-[var(--chat-space-xs)] py-[var(--chat-space-xs)] rounded chat-text-xs text-fg-secondary" {...props}>
          {children}
        </code>
      );
    },
  }), [resolved]);

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
        return (
          <ToolCallView
            key={`tc-${block.toolCallId || block.timestamp}`}
            name={block.name}
            args={block.args}
            result={block.result}
            status={block.status}
            durationMs={block.durationMs}
            workerEvents={block.workerEvents}
          />
        );
      case 'file_edit':
        return <FileEditView key={`edit-${block.edit.tool_call_id || block.timestamp}`} edit={block.edit} compact />;
      case 'image':
        return (
          <img
            key={`img-${block.timestamp}`}
            src={`data:image/png;base64,${block.base64}`}
            alt="tool screenshot"
            loading="lazy"
            decoding="async"
            className="max-w-full max-h-40 rounded mb-[var(--chat-space-sm)] object-contain"
          />
        );
      case 'plan_questions':
        return null;
      case 'plan_answers':
        return null;
      case 'plan_execution':
        return (
          <PlanExecutionCard
            key={`pe-${block.timestamp}`}
            goal={block.goal || planState.goal}
            todos={block.todos}
            phase={planState.phase}
            compact
            onPause={onPauseBuild}
            onEnd={onEndBuild}
            onContinue={onBuildPlan}
          />
        );
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
  }, [planState, onUpdatePlanDecision, onBuildPlan, onPauseBuild, onEndBuild, onViewPlan, markdownComponents]);

  const itemContent = useCallback((index: number) => {
    const msg = filteredMessages[index];
    if (!msg) return null;
    const lastMsg = messages[messages.length - 1];
    const lastAssistantMsgId = lastMsg?.role === 'assistant' && !lastMsg?.isTool ? lastMsg.id : null;
    // Stable per-message key: streamed token updates change the `msg`/`data`
    // identity (appendBlock returns a fresh array + message object), which is
    // what drives Virtuoso to re-render. Keying by content hash instead would
    // remount the row on every token, destroying ReasoningBlock local state
    // (expand/collapse, timer, auto-scroll) and causing the "blinking" bug.
    return (
      <div key={msg.id} className="px-[var(--chat-space-lg)] pb-[var(--chat-message-gap)]">
        <ChatMessageItem
          msg={msg}
          index={index}
          totalCount={filteredMessages.length}
          lastAssistantMsgId={lastAssistantMsgId}
          onRetry={onRetry}
          isRunning={isRunning}
          expandedToolDetails={expandedToolDetails}
          showAllToolDetails={showAllToolDetails}
          onToggleToolDetails={(msgId) =>
            setExpandedToolDetails((prev) => ({ ...prev, [msgId]: !prev[msgId] }))
          }
          onToggleShowAll={(msgId) =>
            setShowAllToolDetails((prev) => ({ ...prev, [msgId]: true }))
          }
          hideToolNoise={hideToolNoise}
          planState={planState}
          onUpdatePlanDecision={onUpdatePlanDecision}
          onBuildPlan={onBuildPlan}
          markdownComponents={markdownComponents}
          renderBlock={renderBlock}
          isNoisyToolBlock={isNoisyToolBlock}
          ToolSummaryRow={ToolSummaryRow}
          ReasoningBlock={ReasoningBlock}
        />
      </div>
    );
  }, [filteredMessages, messages, onRetry, isRunning, expandedToolDetails, showAllToolDetails, hideToolNoise, planState, onUpdatePlanDecision, onBuildPlan, markdownComponents, renderBlock]);

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
              <div className="pl-1 chat-text-xs text-fg-muted flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 animate-spin text-accent" />
                <span>Agent is working...</span>
              </div>
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
          />
        )
      : null,
  }), [agentType, chatMode, isRunning, messages.length, planTaskRequirement, projectName]);

  return (
    <div className="relative h-full min-h-0 flex flex-col overflow-hidden bg-app" data-density={density}>
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

      {/* 消息列表 */}
      <div className="min-h-0 flex-1 relative overflow-hidden">
        <Virtuoso
          ref={virtuosoRef}
          className="h-full"
          data={filteredMessages}
          followOutput={isNearBottom ? 'smooth' : false}
          atBottomStateChange={(atBottom) => setIsNearBottom(atBottom)}
          overscan={200}
          itemContent={itemContent}
          components={virtuosoComponents}
        />
      </div>

      {/* Scroll to bottom button */}
      {!isNearBottom && messages.length > 0 && (
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

            {/* Executing: live todo progress strip */}
            {planState.phase === 'executing' && planState.todos.length > 0 && (
              <div className="mt-1.5 space-y-0.5">
                {planState.todos.slice(0, 5).map((t) => (
                  <div key={t.id} className="flex items-center gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      t.status === 'completed' ? 'bg-success' :
                      t.status === 'in_progress' ? 'bg-accent animate-pulse' :
                      t.status === 'blocked' ? 'bg-danger' :
                      'bg-border'
                    }`} />
                    <span className={`chat-text-xs truncate ${
                      t.status === 'completed' ? 'text-fg-muted line-through' :
                      t.status === 'in_progress' ? 'text-fg' :
                      'text-fg-muted'
                    }`}>
                      {t.title}
                    </span>
                  </div>
                ))}
                {planState.todos.length > 5 && (
                  <div className="chat-text-xs text-fg-muted pl-3">
                    +{planState.todos.length - 5} more
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        <TaskGuidanceQueueCard
          items={taskGuidanceItems}
          isRunning={isRunning}
          onApply={onApplyTaskGuidance}
          onDelete={onDeleteTaskGuidance}
          onClear={onClearTaskGuidance}
        />
        {attachedImage && (
          <div className="mb-2 flex items-center gap-2">
            <div className="relative inline-block">
              <img
                src={`data:image/png;base64,${attachedImage}`}
                alt="preview"
                className="h-16 rounded border border-border"
              />
              <button
                onClick={() => setAttachedImage(null)}
                className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-danger rounded-full text-fg-on-danger text-xs flex items-center justify-center"
                aria-label="Remove image"
              >
                ×
              </button>
            </div>
            <span className="text-xs text-fg-muted">Image attached (will be sent to vision-capable models)</span>
          </div>
        )}

        <div className="flex items-end gap-2">
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
            onChange={handleFileSelect}
            aria-label="Select image to upload"
            title="Select image to upload"
          />

          {/* Voice recording button */}
          {isRecording ? (
            <button
              onClick={stopRecording}
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
              onClick={startRecording}
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
              onChange={(e) => {
                const val = e.target.value;
                setInput(val);
                adjustTextareaHeight();
                // Slash command detection: / at start of input
                if (val.startsWith('/') && !val.includes(' ')) {
                  setSlashQuery(val);
                } else {
                  setSlashQuery('');
                }
                // @Mention detection: @ anywhere in input (look for last @)
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
              }}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder={
                planBlocksChatSend
                  ? 'Complete the plan questions above to continue…'
                  : isRecording
                  ? 'Recording... Click mic to stop'
                  : isTranscribing
                  ? 'Transcribing audio...'
                  : 'Type a message... (Shift+Enter for new line)'
              }
              rows={1}
              className="w-full min-h-[40px] bg-surface-input border border-border rounded-lg px-[var(--chat-space-lg)] py-[var(--chat-space-sm)] pr-10 chat-text-sm text-fg placeholder:text-fg-muted outline-none focus:border-accent resize-none max-h-32 disabled:opacity-60"
            />
            {showSlashMenu && (
              <SlashCommandMenu
                query={slashQuery}
                onSelect={(cmd) => handleCommand(cmd)}
                onClose={() => setSlashQuery('')}
                inputRef={textareaRef}
              />
            )}
            {showAtMenu && (
              <AtMentionMenu
                query={atQuery}
                onSelect={(item) => handleAtMention(item)}
                onClose={() => setAtQuery('')}
                inputRef={textareaRef}
                projectOpen={projectOpen}
                fileTree={fileTree}
              />
            )}
          </div>

          {/* Sandbox mode toggle */}
          <button
            onClick={toggleSandboxMode}
            disabled={isRunning}
            title={sandboxMode === 'sandbox' ? 'Sandbox mode — click for Unrestricted' : 'Unrestricted mode — click for Sandbox'}
            className={`p-2 rounded-lg transition-colors disabled:opacity-50 ${
              sandboxMode === 'sandbox'
                ? 'text-success hover:bg-surface-hover hover:text-success/85'
                : 'text-warning hover:bg-surface-hover hover:text-warning/85'
            }`}
          >
            {sandboxMode === 'sandbox' ? <Shield className="w-5 h-5" /> : <ShieldOff className="w-5 h-5" />}
          </button>

          <button
            onClick={handleSend}
            disabled={planBlocksChatSend || (!input.trim() && !attachedImage)}
            aria-label={isRunning ? 'Queue task guidance' : 'Send'}
            title={
              planBlocksChatSend
                ? 'Send disabled until plan questions are answered'
                : isRunning
                  ? 'Add to task guidance queue'
                  : undefined
            }
            className="p-2 rounded-lg transition-colors bg-accent/85 hover:bg-accent text-fg-on-accent disabled:bg-surface-alt disabled:text-fg-muted"
          >
            <Send className="w-5 h-5" />
          </button>
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
              onCompact={() => onCompact?.(false)}
              disabled={isRunning}
            />
          </div>
        </div>
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
