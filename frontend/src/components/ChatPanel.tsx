import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Send, Image, Loader2, Square, ChevronDown, ChevronRight, RotateCcw, Mic, MicOff, Search, ArrowDown, Shield, ShieldOff } from 'lucide-react';
import { ChatMessage, ToolCall, AssistantBlock } from '../types';
import { API_BASE } from '../config';
import { useTheme } from '../hooks/useTheme';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight, vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { ToolCallView } from './ToolCallView';
import { FileEditView } from './FileEditView';

interface ChatPanelProps {
  messages: ChatMessage[];
  toolCalls: ToolCall[];
  onSend: (text: string, imageBase64?: string) => void;
  onStop?: () => void;
  onRetry?: () => void;
  isRunning: boolean;
  onDraftSave?: (text: string) => void;
  onDraftLoad?: () => Promise<string | undefined>;
  onDraftClear?: () => void;
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
          className="px-[var(--chat-bubble-px)] py-[var(--chat-space-md)] chat-text-sm font-mono text-fg-secondary whitespace-pre-wrap overflow-auto border-t border-border-subtle"
          style={{ maxHeight: '300px', lineHeight: 'var(--chat-line-height)' }}
        >
          {text}
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
}) => {
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
    if (!input.trim() && !attachedImage) return;
    onSend(input.trim(), attachedImage || undefined);
    setInput('');
    setAttachedImage(null);
    onDraftClear?.();
    if (textareaRef.current) {
      textareaRef.current.style.height = '40px';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
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
  const markdownComponents = {
    code({ node, inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || '');
      const language = match ? match[1] : '';
      const value = String(children).replace(/\n$/, '');
      if (!inline && value) {
        return <CodeBlock language={language} value={value} theme={resolved} />;
      }
      return (
        <code className="bg-surface-alt px-[var(--chat-space-xs)] py-[var(--chat-space-xs)] rounded chat-text-xs text-fg-secondary" {...props}>
          {children}
        </code>
      );
    },
  };

  return (
    <div className="h-full flex flex-col bg-app" data-density="compact">
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

      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-[var(--chat-space-lg)] space-y-[var(--chat-message-gap)] relative">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-fg-muted">
            <div className="text-4xl mb-4">🖥️</div>
            <div className="text-lg font-medium mb-2">Desktop Agent Ready</div>
            <div className="text-sm text-center max-w-md">
              I can help you control your computer: manage files, run commands,<br />
              control the browser, operate desktop keyboard &amp; mouse, and interact with other applications.
            </div>
            <div className="mt-6 grid grid-cols-2 gap-2 text-xs">
              <div className="bg-surface px-3 py-2 rounded border border-border text-fg-secondary">Read / Write Files</div>
              <div className="bg-surface px-3 py-2 rounded border border-border text-fg-secondary">Browser Automation</div>
              <div className="bg-surface px-3 py-2 rounded border border-border text-fg-secondary">Keyboard &amp; Mouse</div>
              <div className="bg-surface px-3 py-2 rounded border border-border text-fg-secondary">Window Management</div>
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
                      : 'text-fg-secondary py-[var(--chat-space-xs)]'
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
                        {msg.blocks.map((block, bi) => renderBlock(block, bi))}
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
                className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-red-500 rounded-full text-white text-xs flex items-center justify-center"
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
              className="p-2 rounded-lg transition-colors bg-red-600 hover:bg-red-500 text-white animate-pulse"
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
              disabled={isTranscribing || isRunning}
              className="p-2 text-fg-muted hover:text-fg-secondary hover:bg-surface-hover rounded-lg transition-colors disabled:opacity-50"
              title="Voice input"
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
              disabled={isRecording || isTranscribing}
              onChange={(e) => {
                setInput(e.target.value);
                adjustTextareaHeight();
              }}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder={
                isRecording
                  ? 'Recording... Click mic to stop'
                  : isTranscribing
                  ? 'Transcribing audio...'
                  : 'Type a message... (Shift+Enter for new line)'
              }
              rows={1}
              className="w-full bg-surface-input border border-border rounded-lg px-[var(--chat-space-lg)] py-[var(--chat-space-sm)] pr-10 chat-text-sm text-fg placeholder:text-fg-muted outline-none focus:border-accent resize-none max-h-32 disabled:opacity-60"
              style={{ minHeight: '40px' }}
            />
          </div>

          {/* Sandbox mode toggle */}
          <button
            onClick={toggleSandboxMode}
            disabled={isRunning}
            title={sandboxMode === 'sandbox' ? 'Sandbox mode — click for Unrestricted' : 'Unrestricted mode — click for Sandbox'}
            className={`p-2 rounded-lg transition-colors disabled:opacity-50 ${
              sandboxMode === 'sandbox'
                ? 'text-green-500 hover:bg-surface-hover hover:text-green-400'
                : 'text-orange-500 hover:bg-surface-hover hover:text-orange-400'
            }`}
          >
            {sandboxMode === 'sandbox' ? <Shield className="w-5 h-5" /> : <ShieldOff className="w-5 h-5" />}
          </button>

          <button
            onClick={isRunning ? onStop : handleSend}
            disabled={!isRunning && !input.trim() && !attachedImage}
            aria-label={isRunning ? 'Stop' : 'Send'}
            className={`p-2 rounded-lg transition-colors ${
              isRunning
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : 'bg-accent/85 hover:bg-accent text-white disabled:bg-surface-alt disabled:text-fg-muted'
            }`}
          >
            {isRunning ? <Square className="w-5 h-5" /> : <Send className="w-5 h-5" />}
          </button>
        </div>
      </div>
    </div>
  );
};
