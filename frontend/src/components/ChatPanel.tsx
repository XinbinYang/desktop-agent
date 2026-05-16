import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Image, Loader2, Square, ChevronDown, ChevronRight, RotateCcw, Mic, MicOff, Search, ArrowDown, Shield, ShieldOff } from 'lucide-react';
import {
  ChatMessage,
  ToolCall,
  AssistantBlock,
  ToolSummary,
  ClientChatMode,
  ThinkingIntensity,
  PlanQuestion,
  PlanState,
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
  projectOpen?: boolean;
  fileTree?: any[];
}

type OutputMode = 'concise' | 'balanced' | 'verbose';

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

const PlanQuestionCard: React.FC<{
  question: PlanQuestion;
  onChange: (selected: string[]) => void;
}> = ({ question, onChange }) => {
  const selected = question.selected || [];
  const allowMultiple = question.allow_multiple === true;
  return (
    <div className="rounded-md border border-border-subtle bg-surface px-3 py-2">
      <div className="chat-text-sm text-fg mb-1">{question.prompt}</div>
      <div className="space-y-1">
        {question.options.map((opt) => {
          const checked = selected.includes(opt.id);
          return (
            <label key={opt.id} className="flex items-center gap-2 chat-text-xs text-fg-secondary cursor-pointer">
              <input
                type={allowMultiple ? 'checkbox' : 'radio'}
                name={question.id}
                checked={checked}
                onChange={() => {
                  if (allowMultiple) {
                    onChange(checked ? selected.filter((s) => s !== opt.id) : [...selected, opt.id]);
                    return;
                  }
                  onChange([opt.id]);
                }}
              />
              <span>{opt.label}</span>
            </label>
          );
        })}
      </div>
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

  const scrollRef = useRef<HTMLDivElement>(null);
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

  // 智能滚动检测
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const threshold = 50;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    setIsNearBottom(nearBottom);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener('scroll', handleScroll);
    return () => el.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  // 新消息时自动滚动到底部
  useEffect(() => {
    if (isNearBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isNearBottom]);

  const scrollToBottom = () => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      setIsNearBottom(true);
    }
  };

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
    } else if (cmd.name === 'help') {
      onCommand?.('help', '');
      setInput('');
    } else if (cmd.name === 'compact') {
      onCommand?.('compact', '');
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
  const filteredMessages = searchQuery.trim()
    ? messages.filter((m) => m.content.toLowerCase().includes(searchQuery.toLowerCase()))
    : messages;

  // Markdown 自定义渲染
  // react-markdown v9 中 fenced code blocks 由 pre 组件包裹，code 组件仅处理 inline code。
  const markdownComponents = {
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
  };

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
              ? 'bg-info/12 border-info/30 text-info'
              : 'bg-surface border-border-subtle text-fg-muted hover:text-fg-secondary'
          }`}
        >
          {hideToolNoise ? 'Noise filter: ON' : 'Noise filter: OFF'}
        </button>
      </div>

      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-[var(--chat-space-lg)] space-y-[var(--chat-message-gap)] relative">
        {chatMode === 'plan' && (planState.goal || planState.draft) && (
          <div className="sticky top-0 z-20 mb-2 rounded-md border border-accent/30 bg-surface/95 backdrop-blur px-3 py-2">
            <div className="chat-text-xs text-fg-secondary">
              <span className="text-fg font-medium">Task requirement:</span>{' '}
              {planState.goal || planState.draft.split('\n')[0]?.replace(/^Goal:\s*/, '') || ''}
            </div>
          </div>
        )}
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-fg-muted">
            <div className="text-4xl mb-4">🖥️</div>
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
        )}

        {/* Render a single inline block (thinking / tool_call / image) */}
        {(() => {
          const renderBlock = (block: AssistantBlock, _bi: number) => {
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
                    className="max-w-full max-h-40 rounded mb-[var(--chat-space-sm)] object-contain"
                  />
                );
              default:
                return null;
            }
          };

          {/* 时间线消息列表 */}
          return (
            <div className="space-y-0.5">
              {filteredMessages.map((msg, index) => (
                <div key={msg.id} className="relative pl-[var(--chat-timeline-indent)]">
                  {/* 左侧竖线 */}
                  {index < filteredMessages.length - 1 && (
                    <div className="absolute left-[5px] top-2.5 bottom-0 w-px bg-border-subtle" />
                  )}
                  {/* 小圆点 */}
                  <div className={`absolute left-[2px] top-2 w-1.5 h-1.5 rounded-full ${
                    msg.role === 'user' ? 'bg-accent' : msg.role === 'system' ? 'bg-danger' : 'bg-fg-muted'
                  }`} />

                  <div className={`relative group ${
                    msg.role === 'user'
                      ? 'bg-accent/15 text-fg rounded-lg px-[var(--chat-bubble-px)] py-[var(--chat-bubble-py)] ml-auto max-w-[85%] border border-accent/20 chat-text-sm'
                      : msg.role === 'system'
                      ? 'bg-danger/10 text-danger rounded px-[var(--chat-bubble-px)] py-[var(--chat-space-xs)] chat-text-xs border border-danger/20'
                      : 'text-fg py-[var(--chat-space-xs)]'
                  }`}>
                    {/* Retry button */}
                    {msg.role === 'assistant' && !msg.isTool && onRetry && !isRunning && msg.id === messages[messages.length - 1]?.id && (
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

                    {msg.imageBase64 && (
                      <img
                        src={`data:image/png;base64,${msg.imageBase64}`}
                        alt="attached"
                        className="max-w-full max-h-40 rounded mb-[var(--chat-space-sm)] object-contain"
                      />
                    )}

                    {msg.role === 'assistant' && msg.skill && !msg.isTool && (
                      <div className="flex items-center gap-1 mb-[var(--chat-space-xs)]">
                        <span className="text-[10px] bg-info/15 text-info px-1.5 py-0 rounded border border-info/30">
                          {msg.skill}
                        </span>
                      </div>
                    )}

                    {/* New: render blocks inline (primary path for assistant messages) */}
                    {msg.role === 'assistant' && msg.blocks && msg.blocks.length > 0 ? (
                      <div className="space-y-[var(--chat-block-gap)]">
                        {(() => {
                          const toolBlocks = msg.blocks.filter(
                            (block): block is Extract<AssistantBlock, { type: 'tool_call' }> => block.type === 'tool_call'
                          );
                          const nonToolBlocks = msg.blocks.filter((block) => block.type !== 'tool_call');
                          const isExpanded = expandedToolDetails[msg.id] === true;
                          const showAll = showAllToolDetails[msg.id] === true;
                          const filteredToolBlocks =
                            hideToolNoise && !showAll
                              ? toolBlocks.filter((block) => !isNoisyToolBlock(block))
                              : toolBlocks;
                          const hiddenCount = Math.max(toolBlocks.length - filteredToolBlocks.length, 0);

                          return (
                            <>
                              {nonToolBlocks.map((block, bi) => renderBlock(block, bi))}
                              {msg.toolSummary && toolBlocks.length > 0 && (
                                <ToolSummaryRow
                                  summary={msg.toolSummary}
                                  expanded={isExpanded}
                                  onToggle={() =>
                                    setExpandedToolDetails((prev) => ({ ...prev, [msg.id]: !isExpanded }))
                                  }
                                />
                              )}
                              {toolBlocks.length > 0 && (isExpanded || !msg.toolSummary) && (
                                <div className="space-y-[var(--chat-block-gap)]">
                                  {filteredToolBlocks.map((block, bi) => renderBlock(block, bi))}
                                  {hiddenCount > 0 && (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setShowAllToolDetails((prev) => ({ ...prev, [msg.id]: true }))
                                      }
                                      className="chat-text-xs text-fg-muted hover:text-fg-secondary border border-border-subtle rounded px-2 py-1 bg-surface"
                                    >
                                      Show {hiddenCount} hidden read/search/list calls
                                    </button>
                                  )}
                                </div>
                              )}
                            </>
                          );
                        })()}
                      </div>
                    ) : msg.role === 'assistant' && msg.reasoning ? (
                      /* Fallback: old sessions without blocks */
                      <>
                        <ReasoningBlock text={msg.reasoning} />
                        {msg.content && (
                          <div className="prose prose-sm chat-prose max-w-none">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                              {msg.content}
                            </ReactMarkdown>
                          </div>
                        )}
                      </>
                    ) : msg.isTool ? (
                      <div className="flex items-center gap-2 text-xs text-fg-muted">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        <span>Working...</span>
                      </div>
                    ) : msg.role === 'assistant' && msg.content ? (
                      <div className="prose prose-sm chat-prose max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                          {msg.content}
                        </ReactMarkdown>
                      </div>
                    ) : msg.role === 'user' && msg.content ? (
                      <div className="prose prose-sm chat-prose chat-prose-plain max-w-none">
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                      </div>
                    ) : msg.content ? (
                      <span>{msg.content}</span>
                    ) : null}
                  </div>
                </div>
              ))}

              {isRunning && (
                <div className="relative pl-[var(--chat-timeline-indent)] py-[var(--chat-space-xs)]">
                  <div className="absolute left-[5px] top-0 bottom-0 w-px bg-border-subtle" />
                  <div className="absolute left-[2px] top-1.5 w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
                  <div className="pl-1 chat-text-xs text-fg-muted flex items-center gap-1.5">
                    <Loader2 className="w-3 h-3 animate-spin text-accent" />
                    <span>Agent is working...</span>
                  </div>
                </div>
              )}
            </div>
          );
        })()}
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
        {chatMode === 'plan' && (
          <div
            className="mb-2 rounded-lg border px-3 py-1.5 chat-text-xs text-fg border-[color-mix(in_srgb,var(--plan-pill-border)_55%,transparent)] bg-[color-mix(in_srgb,var(--plan-pill-bg)_18%,var(--bg-surface))]"
            role="status"
          >
            <span className="font-medium">Plan mode</span>
            {' — '}
            Your next message follows the Plan flow (clarify → draft → approve → build).
          </div>
        )}
        {planBlocksChatSend && (
          <div
            className="mb-2 rounded-lg border border-warning/35 bg-warning/10 px-3 py-1.5 chat-text-xs text-warning"
            role="alert"
          >
            Please complete the questions above before sending a new chat message.
          </div>
        )}
        {chatMode === 'plan' && (
          <div className="mb-2 rounded-md border border-info/25 bg-info/8 px-3 py-2 space-y-2">
            {/* ── Phase: clarifying / planning ── */}
            {(planState.phase === 'clarifying' || planState.phase === 'planning') && (
              <div className="flex items-center gap-2 chat-text-xs text-fg-muted">
                <span className="inline-block w-2 h-2 rounded-full bg-accent animate-pulse" />
                Researching & planning{planState.goal ? `: ${planState.goal.slice(0, 100)}` : '…'}
              </div>
            )}

            {/* ── Phase: awaiting_decision (structured questions) ── */}
            {planState.phase === 'awaiting_decision' && (
              <>
                {planState.pending_clarification && (
                  <div className="chat-text-xs text-warning/90 border border-warning/25 rounded px-2 py-1 bg-warning/8">
                    Please answer the questions below to continue.
                  </div>
                )}
                {planState.questions.length > 0 && (
                  <div className="space-y-2">
                    {planState.questions.map((q) => (
                      <PlanQuestionCard
                        key={q.id}
                        question={q}
                        onChange={(selected) => onUpdatePlanDecision(q.id, selected)}
                      />
                    ))}
                  </div>
                )}
              </>
            )}

            {/* ── Phase: awaiting_approval — plan draft + Build button ── */}
            {planState.phase === 'awaiting_approval' && (
              <>
                {planState.plan_file_path && (
                  <div className="flex items-center justify-between chat-text-xs text-fg-muted bg-surface rounded px-2 py-1">
                    <span className="truncate" title={planState.plan_file_path}>
                      Plan: {planState.plan_file_path}
                    </span>
                    <button
                      type="button"
                      className="ml-2 px-2 py-0.5 rounded border border-border text-fg-secondary hover:text-fg hover:border-fg-muted shrink-0"
                      onClick={() => {
                        if (typeof window !== 'undefined' && (window as any).electronAPI?.openPath) {
                          (window as any).electronAPI.openPath(planState.plan_file_path);
                        }
                      }}
                      title="Open plan file in editor"
                    >
                      Open
                    </button>
                  </div>
                )}
                {planState.draft && (
                  <div className="chat-text-xs text-fg-secondary max-h-64 overflow-y-auto">
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {planState.draft.slice(0, 4000) + (planState.draft.length > 4000 ? '\n\n*[truncated]*' : '')}
                      </ReactMarkdown>
                    </div>
                  </div>
                )}
                {planState.todos.length > 0 && (
                  <details className="chat-text-xs text-fg-muted">
                    <summary className="cursor-pointer text-fg-secondary">To-Do ({planState.todos.length})</summary>
                    <div className="mt-1 space-y-1">
                      {planState.todos.map((t) => (
                        <div key={t.id} className="text-fg-muted">
                          [{t.status}] {t.title}
                          {t.depends_on && t.depends_on.length > 0 && (
                            <span className="block text-[10px] text-fg-muted mt-0.5">
                              Depends on: {t.depends_on.join(', ')}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </details>
                )}
                <button
                  type="button"
                  onClick={onBuildPlan}
                  className="chat-text-xs w-full px-3 py-2 rounded font-medium bg-accent text-fg-on-accent hover:brightness-110 transition"
                  title="Approve plan and start execution"
                >
                  Start Build
                </button>
                <div className="chat-text-xs text-fg-muted text-center">
                  Not what you expected? Describe changes in chat and I&apos;ll revise the plan.
                </div>
              </>
            )}

            {/* ── Phase: approved_waiting_build / executing ── */}
            {(planState.phase === 'approved_waiting_build' || planState.phase === 'executing') && (
              <>
                <div className="flex items-center gap-2 chat-text-xs text-accent font-medium">
                  <span className="inline-block w-2 h-2 rounded-full bg-accent animate-pulse" />
                  Executing plan{planState.goal ? `: ${planState.goal.slice(0, 80)}` : '…'}
                </div>
                {planState.todos.length > 0 && (
                  <div className="rounded border border-border-subtle bg-surface px-2 py-1">
                    <div className="chat-text-xs text-fg-secondary mb-1">To-Do</div>
                    <div className="space-y-1">
                      {planState.todos.map((t) => (
                        <div key={t.id} className="chat-text-xs text-fg-muted">
                          <span className="text-fg-secondary">[{t.status}]</span> {t.title}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
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
                className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-danger rounded-full text-white text-xs flex items-center justify-center"
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
              className="p-2 rounded-lg transition-colors bg-danger hover:bg-danger/85 text-white animate-pulse"
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
                ? 'bg-danger hover:bg-danger/85 text-white'
                : 'bg-accent/85 hover:bg-accent text-white disabled:bg-surface-alt disabled:text-fg-muted'
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
            <span className="chat-text-xs text-fg-muted">Thinking</span>
            {(['low', 'medium', 'high'] as ThinkingIntensity[]).map((level) => (
              <button
                key={level}
                type="button"
                onClick={() => onThinkingIntensityChange(level)}
                className={`chat-text-xs px-2 py-0.5 rounded border transition-colors ${
                  thinkingIntensity === level
                    ? 'bg-info/12 border-info/30 text-info'
                    : 'bg-surface border-border-subtle text-fg-muted hover:text-fg-secondary'
                }`}
              >
                {level}
              </button>
            ))}
            <span className="chat-text-xs text-fg-muted ml-1" title="Server plan phase">
              Status: {planPhaseLabel(planState.phase)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
