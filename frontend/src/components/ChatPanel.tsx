import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { Send, Image, Loader2, Square, ChevronDown, ChevronRight, RotateCcw, Mic, MicOff, Search, ArrowDown, Shield, ShieldOff, BookOpen, Check } from 'lucide-react';
import { Virtuoso, VirtuosoHandle } from 'react-virtuoso';
import {
  ChatMessage,
  ToolCall,
  AssistantBlock,
  ToolSummary,
  ClientChatMode,
  ThinkingIntensity,
  PlanQuestion,
  PlanState,
  PlanTodo,
  ContextUsage,
  ConversationCheckpoint,
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
  onRejectPlan: () => void;
  onUpdatePlanDecision: (questionId: string, selected: string[]) => void;
  onCommand?: (command: string, args: string) => void;
  contextUsage?: ContextUsage | null;
  checkpoints?: ConversationCheckpoint[];
  onCompact?: (force?: boolean, focus?: string) => void;
  onClearSession?: () => void;
  onLoadCheckpoints?: () => Promise<ConversationCheckpoint[]>;
  onRewindToCheckpoint?: (checkpointId: string) => void;
  rewindOpen?: boolean;
  onRewindOpenChange?: (open: boolean) => void;
  projectOpen?: boolean;
  fileTree?: any[];
}

type OutputMode = 'concise' | 'balanced' | 'verbose';

const THINKING_LEVELS: ThinkingIntensity[] = ['low', 'medium', 'high'];
const THINKING_LABELS: Record<ThinkingIntensity, string> = {
  low: 'LOW',
  medium: 'MEDIUM',
  high: 'HIGH',
};

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

/** Collapsible thinking/reasoning block */
const ReasoningBlock: React.FC<{ text: string }> = ({ text }) => {
  const [expanded, setExpanded] = useState(false);
  const lineCount = text.split('\n').length;

  return (
    <div className="my-[var(--chat-space-sm)] rounded-md border border-border bg-surface/60 overflow-hidden border-l-2 border-l-info/70">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-1.5 px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-sm text-fg-secondary hover:text-fg hover:bg-surface-hover transition-colors"
      >
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span className="font-medium">Thinking</span>
        <span className="text-fg-muted ml-1 chat-text-xs">({lineCount} lines)</span>
      </button>
      {expanded && (
        <div
          className="px-[var(--chat-bubble-px)] py-[var(--chat-space-md)] font-mono chat-text-xs text-fg-secondary whitespace-pre-wrap overflow-auto border-t border-border-subtle"
          style={{ maxHeight: '300px', lineHeight: 'var(--chat-line-height)' }}
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
const PlanDraftInlineCard: React.FC<{
  block: Extract<AssistantBlock, { type: 'plan_draft' }>;
  planState: PlanState;
  onBuild: () => void;
}> = ({ block, planState, onBuild }) => {
  const isExecuting = ['executing', 'completed', 'approved_waiting_build'].includes(planState.phase);
  const canBuild = planState.phase === 'awaiting_approval' && !planState.approved;
  const [open, setOpen] = useState<Record<string, boolean>>({ todos: true, risks: false, steps: false });
  const toggle = (k: string) => setOpen((prev) => ({ ...prev, [k]: !prev[k] }));

  // Use live todos from planState when executing for real-time status
  const todos: PlanTodo[] = isExecuting && planState.todos.length > 0
    ? planState.todos
    : block.todos;
  const sp = block.structured_plan;

  return (
    <div className="my-2 rounded-xl border border-[color:var(--plan-pill-border)] overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-[color-mix(in_srgb,var(--plan-pill-bg)_18%,var(--bg-surface))] border-b border-[color:var(--plan-pill-border)]/40">
        <div className="flex items-center gap-2 mb-1">
          <PlanModeIcon className="text-[color:var(--plan-pill-fg)] opacity-80 shrink-0" />
          <span className="chat-text-xs font-semibold text-[color:var(--plan-pill-fg)] uppercase tracking-wide">
            Implementation Plan
          </span>
          {isExecuting && (
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

      {/* Tasks section */}
      {todos.length > 0 && (
        <div className="border-b border-border-subtle">
          <button
            type="button"
            onClick={() => toggle('todos')}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-hover transition-colors text-left"
          >
            <span className="chat-text-xs font-medium text-fg-secondary uppercase tracking-wide">
              Tasks ({todos.length})
            </span>
            {open.todos
              ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted" />
              : <ChevronRight className="w-3.5 h-3.5 text-fg-muted" />}
          </button>
          {open.todos && (
            <div className="px-4 pb-3 space-y-2">
              {todos.map((t, i) => {
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

      {/* Steps section */}
      {sp && sp.steps && sp.steps.length > 0 && (
        <div className="border-b border-border-subtle">
          <button
            type="button"
            onClick={() => toggle('steps')}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-hover transition-colors text-left"
          >
            <span className="chat-text-xs font-medium text-fg-secondary uppercase tracking-wide">
              Steps ({sp.steps.length})
            </span>
            {open.steps
              ? <ChevronDown className="w-3.5 h-3.5 text-fg-muted" />
              : <ChevronRight className="w-3.5 h-3.5 text-fg-muted" />}
          </button>
          {open.steps && (
            <div className="px-4 pb-3 space-y-1.5">
              {sp.steps.map((s, i) => (
                <div key={s.id} className="chat-text-xs text-fg-secondary">
                  <span className="font-medium text-fg">{i + 1}.</span> {s.title}
                  {s.details && <div className="mt-0.5 text-fg-muted text-[10px] pl-3">{s.details.slice(0, 120)}</div>}
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

      {/* CTA footer */}
      {canBuild && (
        <div className="px-4 py-3 bg-[color-mix(in_srgb,var(--plan-pill-bg)_8%,var(--bg-surface))] space-y-2">
          <button
            type="button"
            onClick={onBuild}
            className="w-full py-2.5 px-4 rounded-lg bg-accent text-fg-on-accent font-semibold chat-text-sm hover:brightness-110 active:scale-[0.99] transition flex items-center justify-center gap-2"
          >
            ▶ Build
          </button>
          <p className="text-center chat-text-xs text-fg-muted">
            Not right? Describe changes in the chat below and I&apos;ll revise.
          </p>
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
  onRejectPlan,
  onUpdatePlanDecision,
  onCommand,
  contextUsage,
  checkpoints = [],
  onCompact,
  onClearSession,
  onLoadCheckpoints,
  onRewindToCheckpoint,
  rewindOpen = false,
  onRewindOpenChange,
  projectOpen = false,
  fileTree = [],
}) => {
  const planBlocksChatSend = chatMode === 'plan' && planState.phase === 'awaiting_decision';
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
    onSend(input.trim(), attachedImage || undefined, { chatMode, thinkingIntensity });
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
    if (cmd.name === 'clear') {
      onCommand?.('clear', '');
      setInput('');
    } else if (cmd.name === 'new') {
      onCommand?.('new', '');
      setInput('');
    } else if (cmd.name === 'help') {
      onCommand?.('help', '');
      setInput('');
    } else if (cmd.name === 'compact') {
      onCommand?.('compact', cmd.args || '');
      setInput('');
    } else if (cmd.name === 'rewind') {
      onCommand?.('rewind', '');
      setInput('');
    } else if (cmd.name === 'context') {
      onCommand?.('context', '');
      setInput('');
    } else if (cmd.name === 'config') {
      onCommand?.('config', '');
      setInput('');
    } else if (cmd.name === 'screenshot') {
      onCommand?.('screenshot', '');
      setInput('');
    } else {
      // For commands with args, fill the command prefix and let user type args
      setInput(`/${cmd.name} `);
      if (cmd.args) {
        // Focus back on textarea for arg input
        setTimeout(() => textareaRef.current?.focus(), 0);
      }
    }
  }, [onCommand]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
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
        return <ReasoningBlock key={`t-${block.timestamp}`} text={block.text} />;
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
        return (
          <PlanQuestionsInlineCard
            key={`pq-${block.timestamp}`}
            questions={block.questions}
            planState={planState}
            onUpdate={onUpdatePlanDecision}
          />
        );
      case 'plan_draft':
        return (
          <PlanDraftInlineCard
            key={`pd-${block.timestamp}`}
            block={block}
            planState={planState}
            onBuild={onBuildPlan}
          />
        );
      default:
        return null;
    }
  }, [planState, onUpdatePlanDecision, onBuildPlan, markdownComponents]);

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

  const virtuosoComponents: any = useMemo(() => ({
    Header: () => <div className="h-[var(--chat-space-md)]" />,
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
          <div className="flex flex-col items-center justify-center h-full text-fg-muted p-[var(--chat-space-lg)]">
            <div className="text-4xl mb-4">&#x1f5a5;&#xfe0f;</div>
            <div className="text-lg font-medium mb-2 text-fg">Desktop Agent Ready</div>
            <div className="text-sm text-center max-w-md text-fg-secondary">
              I can help you control your computer: manage files, run commands,<br />
              control the browser, operate desktop keyboard &amp; mouse, and interact with other applications.
            </div>
            <div className="mt-6 grid grid-cols-2 gap-2 text-xs">
              <div className="bg-surface px-3 py-2 rounded border border-border text-fg-secondary shadow-sm">Read / Write Files</div>
              <div className="bg-surface px-3 py-2 rounded border border-border text-fg-secondary shadow-sm">Browser Automation</div>
              <div className="bg-surface px-3 py-2 rounded border border-border text-fg-secondary shadow-sm">Keyboard &amp; Mouse</div>
              <div className="bg-surface px-3 py-2 rounded border border-border text-fg-secondary shadow-sm">Window Management</div>
            </div>
          </div>
        )
      : null,
  }), [isRunning, messages.length]);

  return (
    <div className="h-full flex flex-col bg-app" data-density={density}>
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
      <div className="flex-1 relative">
        {chatMode === 'plan' && (planState.goal || planState.draft) && (
          <div className="sticky top-0 z-20 mx-[var(--chat-space-lg)] mt-[var(--chat-space-md)] rounded-md border border-accent/30 bg-surface/95 backdrop-blur px-3 py-2">
            <div className="chat-text-xs text-fg-secondary">
              <span className="text-fg font-medium">Task requirement:</span>{' '}
              {planState.goal || planState.draft.split('\n')[0]?.replace(/^Goal:\s*/, '') || ''}
            </div>
          </div>
        )}
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
      <div className="border-t border-border p-[var(--chat-space-lg)] bg-surface">
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
                    if (typeof window !== 'undefined' && (window as any).electronAPI?.openPath) {
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
        {planBlocksChatSend && (
          <div
            className="mb-2 rounded-lg border border-warning/35 bg-warning/10 px-3 py-1.5 chat-text-xs text-warning"
            role="alert"
          >
            Please complete the questions above before sending a new message.
          </div>
        )}

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
            onClick={isRunning ? onStop : handleSend}
            disabled={!isRunning && (planBlocksChatSend || (!input.trim() && !attachedImage))}
            aria-label={isRunning ? 'Stop' : 'Send'}
            title={planBlocksChatSend ? 'Send disabled until plan questions are answered' : undefined}
            className={`p-2 rounded-lg transition-colors ${
              isRunning
                ? 'bg-danger hover:bg-danger/85 text-fg-on-danger'
                : 'bg-accent/85 hover:bg-accent text-fg-on-accent disabled:bg-surface-alt disabled:text-fg-muted'
            }`}
          >
            {isRunning ? <Square className="w-5 h-5" /> : <Send className="w-5 h-5" />}
          </button>
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
