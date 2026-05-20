import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Virtuoso, VirtuosoHandle } from 'react-virtuoso';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight, vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import {
  AlertCircle,
  ArrowDown,
  Bot,
  BookOpen,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  FileText,
  Maximize2,
  RotateCcw,
  User,
  Wrench,
} from 'lucide-react';
import type { ChatMessage, FileEdit, PlanState, ToolCall } from '../../types';
import {
  buildPersonalConversation,
  type PersonalActivityItem,
  type PersonalConversationItem,
  type PersonalMessageGroup,
} from '../../lib/personalConversation';
import { ToolCallView } from '../ToolCallView';
import { FileEditView } from '../FileEditView';
import { AgentRunningSpinner } from './AgentRunningStatus';
import { RevealableInlineCode } from '../RevealPathAction';

interface ImagePreviewState {
  src: string;
  alt: string;
}

interface PersonalChatSurfaceProps {
  sessionId?: string;
  messages: ChatMessage[];
  toolCalls?: ToolCall[];
  fileEdits?: FileEdit[];
  planState: PlanState;
  searchQuery?: string;
  isRunning: boolean;
  onRetry?: () => void;
  onOpenImage: (preview: ImagePreviewState) => void;
  emptyPlaceholder: React.ReactNode;
  markdownTheme: 'dark' | 'light';
  assistantDisplayName?: string;
  projectPath?: string | null;
}

interface PersonalScrollMemory {
  atBottom?: boolean;
  groupCount: number;
  updatedAt: number;
}

type PersonalTone = 'user' | 'assistant' | 'system-success' | 'system-error';

const personalScrollMemoryBySession = new Map<string, PersonalScrollMemory>();
const LONG_TEXT_LENGTH = 1800;
const CODE_PREVIEW_LINES = 16;

function formatMessageTime(value?: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '';
  try {
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function trimText(value: string, maxChars = LONG_TEXT_LENGTH): string {
  if (value.length <= maxChars) return value;
  return `${value.slice(0, maxChars).trimEnd()}\n...`;
}

function trimCodePreview(value: string, maxLines = CODE_PREVIEW_LINES): string {
  const lines = value.split(/\r?\n/);
  if (lines.length <= maxLines) return value;
  return `${lines.slice(0, maxLines).join('\n')}\n...`;
}

function personalTone(
  role: PersonalMessageGroup['role'],
  noticeLevel?: PersonalConversationItem['noticeLevel'],
): PersonalTone {
  if (role === 'user') return 'user';
  if (role === 'assistant') return 'assistant';
  return noticeLevel === 'success' ? 'system-success' : 'system-error';
}

const PersonalAvatar: React.FC<{
  role: PersonalMessageGroup['role'];
  tone: PersonalTone;
}> = ({ role, tone }) => {
  const isUser = role === 'user';
  const isSystem = role === 'system';
  const isSuccessNotice = tone === 'system-success';
  return (
    <div
      className="personal-chat-avatar mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
      data-tone={tone}
      aria-hidden
    >
      {isSuccessNotice ? <CheckCircle2 className="h-4 w-4" /> : isSystem ? <AlertCircle className="h-4 w-4" /> : isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
    </div>
  );
};

const PersonalImageThumbnail: React.FC<{
  base64: string;
  alt: string;
  onOpen: (preview: ImagePreviewState) => void;
}> = ({ base64, alt, onOpen }) => {
  const src = `data:image/png;base64,${base64}`;
  return (
    <button
      type="button"
      onClick={() => onOpen({ src, alt })}
      className="group/image relative mt-2 block max-w-full cursor-zoom-in overflow-hidden rounded-md border border-border-subtle bg-surface/45 p-0 leading-none focus:outline-none focus:ring-2 focus:ring-accent/60"
      aria-label={alt}
      title={alt}
    >
      <img
        src={src}
        alt={alt}
        loading="lazy"
        decoding="async"
        draggable={false}
        className="block max-h-56 max-w-full rounded object-contain transition-transform duration-150 group-hover/image:scale-[1.01]"
      />
      <span className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded bg-black/55 text-white opacity-0 transition-opacity group-hover/image:opacity-100 group-focus-visible/image:opacity-100">
        <Maximize2 className="h-3.5 w-3.5" />
      </span>
    </button>
  );
};

const PersonalCodeBlock: React.FC<{ language?: string; value: string; theme: 'dark' | 'light' }> = ({
  language,
  value,
  theme,
}) => {
  const [expanded, setExpanded] = useState(false);
  const lines = value.split(/\r?\n/).length;
  const canExpand = lines > CODE_PREVIEW_LINES || value.length > 1600;

  return (
    <div className="my-2 overflow-hidden rounded-md border border-border-subtle bg-surface-alt/80">
      <div className="flex items-center justify-between gap-2 border-b border-border-subtle px-3 py-1.5">
        <span className="chat-text-xs font-medium uppercase text-fg-muted">{language || 'text'}</span>
        {canExpand && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="chat-text-xs text-fg-muted hover:text-fg-secondary"
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
        )}
      </div>
      {expanded ? (
        <SyntaxHighlighter
          language={language || 'text'}
          style={theme === 'dark' ? vscDarkPlus : oneLight}
          customStyle={{
            margin: 0,
            borderRadius: 0,
            fontSize: 'var(--chat-font-sm)',
            lineHeight: 'var(--chat-line-height)',
            padding: 'var(--chat-space-md) var(--chat-space-lg)',
          }}
          wrapLongLines
        >
          {value}
        </SyntaxHighlighter>
      ) : (
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap px-3 py-2 font-mono chat-text-xs text-fg-secondary">
          {canExpand ? trimCodePreview(value) : value}
        </pre>
      )}
    </div>
  );
};

const PersonalMarkdownInner: React.FC<{
  text: string;
  streaming: boolean;
  theme: 'dark' | 'light';
  projectPath?: string | null;
}> = ({ text, streaming, theme, projectPath }) => {
  const [expanded, setExpanded] = useState(false);
  // Render markdown live during streaming so bullets/bold/headings appear with
  // each token. Code blocks fall back to a lightweight <pre> while streaming
  // (Prism syntax highlighting is expensive to initialise per language) and
  // upgrade to the full PersonalCodeBlock once the turn completes.
  //
  // IMPORTANT: All hooks must be called before any early return, otherwise the
  // hook count varies between renders when `text` switches between empty and
  // non-empty — which triggers "Rendered more hooks than during the previous
  // render" inside Virtuoso recycled rows.
  const markdownComponents = useMemo(
    () => ({
      pre({ node, children, ...props }: any) {
        const codeNode = node?.children?.[0];
        if (codeNode?.tagName === 'code') {
          const className = codeNode.properties?.className?.[0] || '';
          const match = /language-(\w+)/.exec(className);
          const value = codeNode.children?.map((child: any) => child.value).join('') || '';
          if (streaming) {
            return (
              <pre className="my-2 max-h-72 overflow-auto rounded-md border border-border-subtle bg-surface-alt/80 px-3 py-2 whitespace-pre-wrap font-mono chat-text-xs text-fg-secondary">
                {value}
              </pre>
            );
          }
          return <PersonalCodeBlock language={match ? match[1] : ''} value={value} theme={theme} />;
        }
        return <pre {...props}>{children}</pre>;
      },
      code({ children, ...props }: any) {
        const value = React.Children.toArray(children).map((child) => String(child)).join('');
        return (
          <RevealableInlineCode
            value={value}
            projectPath={projectPath}
            className="rounded bg-surface-alt px-1 py-0.5 chat-text-xs text-fg-secondary"
          >
            {children}
          </RevealableInlineCode>
        );
      },
    }),
    [streaming, theme, projectPath],
  );

  const long = text.length > LONG_TEXT_LENGTH;
  const visibleText = !expanded && long ? trimText(text) : text;

  if (!text.trim()) return null;

  return (
    <div>
      <div className="prose prose-sm chat-prose max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
          {visibleText}
        </ReactMarkdown>
      </div>
      {long && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-1 chat-text-xs font-medium text-accent hover:text-accent/80"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
};

const PersonalMarkdown = React.memo(
  PersonalMarkdownInner,
  (prev, next) =>
    prev.text === next.text && prev.streaming === next.streaming && prev.theme === next.theme && prev.projectPath === next.projectPath,
);

function activityIcon(activity: PersonalActivityItem) {
  if (activity.status === 'running') return <AgentRunningSpinner className="h-3.5 w-3.5 text-info" />;
  if (activity.status === 'error') return <AlertCircle className="h-3.5 w-3.5 text-danger" />;
  if (activity.kind === 'thinking') return <Brain className="h-3.5 w-3.5 text-info" />;
  if (activity.kind === 'knowledge') return <BookOpen className="h-3.5 w-3.5 text-accent" />;
  if (activity.kind === 'file_edit') return <FileText className="h-3.5 w-3.5 text-success" />;
  if (activity.kind === 'plan') return <ClipboardList className="h-3.5 w-3.5 text-accent" />;
  if (activity.status === 'success') return <CheckCircle2 className="h-3.5 w-3.5 text-success" />;
  return <Wrench className="h-3.5 w-3.5 text-fg-muted" />;
}

function activityStepCount(activity: PersonalActivityItem): number {
  if (activity.kind === 'tool') return activity.tools?.length || activity.count || 1;
  return 1;
}

function parseThoughtDurationSeconds(label: string): number {
  const match = /Thought for (?:(\d+)m(?:\s+(\d+)s)?|(\d+)s)/.exec(label);
  if (!match) return 0;
  const minutes = Number(match[1] || 0);
  const seconds = Number(match[2] || match[3] || 0);
  return minutes * 60 + seconds;
}

function formatChineseDuration(totalSeconds: number): string {
  if (totalSeconds < 60) return `${totalSeconds} 秒`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds === 0 ? `${minutes} 分钟` : `${minutes} 分 ${seconds} 秒`;
}

function summarizeActivities(activities: PersonalActivityItem[], running: boolean): string {
  const stepCount = Math.max(1, activities.reduce((sum, activity) => sum + activityStepCount(activity), 0));
  const thinkingActivities = activities.filter((activity) => activity.kind === 'thinking');
  const thinkingSeconds = thinkingActivities.reduce(
    (sum, activity) => sum + parseThoughtDurationSeconds(activity.label),
    0,
  );
  const toolCount = activities
    .filter((activity) => activity.kind === 'tool')
    .reduce((sum, activity) => sum + (activity.tools?.length || activity.count || 1), 0);
  const memorySourceCount = activities
    .filter((activity) => activity.kind === 'knowledge')
    .reduce((sum, activity) => sum + (activity.sources?.length || activity.count || 1), 0);
  const fileEditCount = activities.filter((activity) => activity.kind === 'file_edit').length;
  const planCount = activities.filter((activity) => activity.kind === 'plan').length;
  const errorCount = activities.filter((activity) => activity.status === 'error').length;
  const details: string[] = [];

  if (thinkingSeconds > 0) {
    details.push(`思考 ${formatChineseDuration(thinkingSeconds)}`);
  } else if (thinkingActivities.length > 0) {
    details.push(`思考 ${thinkingActivities.length} 次`);
  }
  if (memorySourceCount > 0) details.push(`查了 ${memorySourceCount} 条记忆`);
  if (toolCount > 0) details.push(`用了 ${toolCount} 个工具`);
  if (fileEditCount > 0) details.push(`修改 ${fileEditCount} 个文件`);
  if (planCount > 0) details.push(`更新 ${planCount} 个计划`);
  if (errorCount > 0) details.push(`${errorCount} 个异常`);

  return [running ? `正在处理 ${stepCount} 步` : `我处理了 ${stepCount} 步`, ...details].join(' · ');
}

const ActivityDetails: React.FC<{ activity: PersonalActivityItem; projectPath?: string | null }> = ({ activity, projectPath }) => {
  if (activity.kind === 'tool' && activity.tools?.length) {
    return (
      <div className="mt-1.5 space-y-1.5">
        {activity.tools.map((tool) => (
          <ToolCallView
            key={tool.id}
            name={tool.name}
            args={tool.args}
            result={tool.result}
            status={tool.status}
            durationMs={tool.durationMs}
            workerEvents={tool.workerEvents}
            variant="disclosure"
            projectPath={projectPath}
          />
        ))}
      </div>
    );
  }

  if (activity.kind === 'knowledge' && activity.sources?.length) {
    return (
      <div className="mt-1.5 rounded-md border border-border-subtle bg-surface/55 px-3 py-2">
        {activity.sources.slice(0, 5).map((source) => (
          <div key={`${source.source_path}:${source.score}`} className="chat-text-xs text-fg-secondary">
            <span className="font-medium text-fg">{source.source_path}</span>
            {source.preview && <span className="text-fg-muted"> - {source.preview}</span>}
          </div>
        ))}
      </div>
    );
  }

  if (activity.kind === 'file_edit' && activity.edit) {
    return (
      <div className="mt-1.5">
        <FileEditView edit={activity.edit} compact variant="event-row" projectPath={projectPath} />
      </div>
    );
  }

  if (activity.text) {
    return (
      <div className="mt-1.5 max-h-60 overflow-auto whitespace-pre-wrap rounded-md border border-border-subtle bg-surface/55 px-3 py-2 chat-text-sm text-fg-secondary">
        {activity.text}
      </div>
    );
  }

  return null;
};

const ActivityChip: React.FC<{ activity: PersonalActivityItem; projectPath?: string | null }> = ({ activity, projectPath }) => {
  const [open, setOpen] = useState(false);
  const hasDetails = !!(
    activity.text ||
    activity.tools?.length ||
    activity.sources?.length ||
    activity.edit
  );

  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={() => hasDetails && setOpen((value) => !value)}
        className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 chat-text-xs transition-colors ${
          activity.status === 'error'
            ? 'border-danger/25 bg-danger/10 text-danger'
            : activity.status === 'running'
              ? 'border-info/25 bg-info/10 text-info'
              : 'border-border-subtle bg-surface/55 text-fg-secondary hover:bg-surface-hover'
        } ${hasDetails ? 'cursor-pointer' : 'cursor-default'}`}
      >
        {activityIcon(activity)}
        <span className="truncate">{activity.label}</span>
        {hasDetails && (open ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />)}
      </button>
      {open && <ActivityDetails activity={activity} projectPath={projectPath} />}
    </div>
  );
};

const PersonalActivityDrawer: React.FC<{
  activities: PersonalActivityItem[];
  turnComplete?: boolean;
  searchQuery?: string;
  projectPath?: string | null;
}> = ({ activities, turnComplete, searchQuery = '', projectPath }) => {
  const [manualOpen, setManualOpen] = useState<boolean | null>(null);
  const query = searchQuery.trim().toLowerCase();
  const hasRunning = activities.some((activity) => activity.status === 'running');
  const defaultOpen = hasRunning || turnComplete === false;
  const forceOpenForSearch = !!query && activities.some((activity) => activityMatchesSearch(activity, query));
  const open = forceOpenForSearch || (manualOpen ?? defaultOpen);
  const summary = summarizeActivities(activities, hasRunning || turnComplete === false);

  if (activities.length === 0) return null;

  return (
    <div className="mt-2 min-w-0" data-testid="personal-activity-drawer">
      <button
        type="button"
        aria-expanded={open}
        aria-label={open ? '折叠处理过程' : '展开处理过程'}
        onClick={() => {
          if (forceOpenForSearch) return;
          setManualOpen((value) => !(value ?? defaultOpen));
        }}
        className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border-subtle bg-surface/55 px-2.5 py-1 chat-text-xs text-fg-muted transition-colors hover:bg-surface-hover hover:text-fg-secondary"
      >
        <ClipboardList className="h-3.5 w-3.5 shrink-0 text-fg-muted" />
        <span className="truncate">{summary}</span>
        {open ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
      </button>
      {open && (
        <div className="mt-1.5 flex flex-col items-start gap-1.5">
          {activities.map((activity) => (
            <ActivityChip key={activity.id} activity={activity} projectPath={projectPath} />
          ))}
        </div>
      )}
    </div>
  );
};

const PersonalMessageItem: React.FC<{
  item: PersonalConversationItem;
  isLastAssistant: boolean;
  isRunning: boolean;
  onRetry?: () => void;
  onOpenImage: (preview: ImagePreviewState) => void;
  markdownTheme: 'dark' | 'light';
  searchQuery?: string;
  projectPath?: string | null;
}> = ({ item, isLastAssistant, isRunning, onRetry, onOpenImage, markdownTheme, searchQuery, projectPath }) => {
  const canRetry = item.role === 'assistant' && isLastAssistant && !!onRetry && !isRunning && item.turnComplete !== false;
  const tone = personalTone(item.role, item.noticeLevel);

  return (
    <div className="personal-chat-message group/message relative min-w-0" data-role={item.role} data-tone={tone}>
      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          title="Regenerate"
          aria-label="Regenerate"
          className="absolute -right-1 -top-1 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface-alt text-fg-muted opacity-0 transition-opacity hover:bg-surface-hover hover:text-fg-secondary group-hover/message:opacity-100"
        >
          <RotateCcw className="h-3 w-3" />
        </button>
      )}
      <div className={item.role === 'system' ? (item.noticeLevel === 'success' ? 'text-success' : 'text-danger') : 'text-fg'}>
        <PersonalMarkdown text={item.text} streaming={item.isStreaming} theme={markdownTheme} projectPath={projectPath} />
        {item.images.map((base64, index) => (
          <PersonalImageThumbnail
            key={`${item.id}:image:${index}`}
            base64={base64}
            alt={item.role === 'user' ? 'Open attached image' : 'Open assistant image'}
            onOpen={onOpenImage}
          />
        ))}
        {item.activities.length > 0 && (
          <PersonalActivityDrawer
            activities={item.activities}
            turnComplete={item.turnComplete}
            searchQuery={searchQuery}
            projectPath={projectPath}
          />
        )}
      </div>
    </div>
  );
};

const PersonalGroupRow: React.FC<{
  group: PersonalMessageGroup;
  lastAssistantItemId: string;
  isRunning: boolean;
  onRetry?: () => void;
  onOpenImage: (preview: ImagePreviewState) => void;
  markdownTheme: 'dark' | 'light';
  searchQuery?: string;
  projectPath?: string | null;
}> = ({ group, lastAssistantItemId, isRunning, onRetry, onOpenImage, markdownTheme, searchQuery, projectPath }) => {
  const timeLabel = formatMessageTime(group.startedAt);
  const tone = personalTone(group.role, group.items[0]?.noticeLevel);

  return (
    <div
      className="personal-chat-row px-4 py-1.5 transition-colors"
      data-role={group.role}
      data-tone={tone}
    >
      <div className="personal-chat-row-inner mx-auto flex w-full max-w-5xl gap-3 px-1 sm:px-2">
        <PersonalAvatar role={group.role} tone={tone} />
        <div className="min-w-0 flex-1">
          <div className="mb-0.5 flex min-w-0 items-baseline gap-2">
            <span className="personal-chat-author" data-role={group.role} data-tone={tone}>{group.authorName}</span>
            {timeLabel && <span className="personal-chat-timestamp">{timeLabel}</span>}
          </div>
          <div className="space-y-2">
            {group.items.map((item) => (
              <PersonalMessageItem
                key={item.id}
                item={item}
                isLastAssistant={item.id === lastAssistantItemId}
                isRunning={isRunning}
                onRetry={onRetry}
                onOpenImage={onOpenImage}
                markdownTheme={markdownTheme}
                searchQuery={searchQuery}
                projectPath={projectPath}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

function safeSearchText(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function activityMatchesSearch(activity: PersonalActivityItem, query: string): boolean {
  const haystack = [
    activity.label,
    activity.text,
    activity.edit?.path,
    activity.edit?.operation,
    activity.edit?.unified_diff,
    ...(activity.sources || []).flatMap((source) => [
      source.source_path,
      source.preview,
      source.score,
    ]),
    ...(activity.tools || []).flatMap((tool) => [
      tool.name,
      safeSearchText(tool.args),
      tool.result,
    ]),
  ].map(safeSearchText).join('\n').toLowerCase();
  return haystack.includes(query);
}

function itemMatchesSearch(item: PersonalConversationItem, query: string): boolean {
  const haystack = [
    item.text,
    item.authorName,
    item.source,
    item.noticeLevel,
  ].map(safeSearchText).join('\n').toLowerCase();
  return haystack.includes(query) || item.activities.some((activity) => activityMatchesSearch(activity, query));
}

function filterGroupsBySearch(groups: PersonalMessageGroup[], searchQuery?: string): PersonalMessageGroup[] {
  const query = (searchQuery || '').trim().toLowerCase();
  if (!query) return groups;
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => itemMatchesSearch(item, query)),
    }))
    .filter((group) => group.items.length > 0);
}

export const PersonalChatSurface: React.FC<PersonalChatSurfaceProps> = ({
  sessionId,
  messages,
  toolCalls = [],
  fileEdits = [],
  planState,
  searchQuery = '',
  isRunning,
  onRetry,
  onOpenImage,
  emptyPlaceholder,
  markdownTheme,
  assistantDisplayName = 'Personal Agent',
  projectPath = null,
}) => {
  const allGroups = useMemo(
    () => buildPersonalConversation({ messages, toolCalls, fileEdits, planState, assistantDisplayName }),
    [messages, toolCalls, fileEdits, planState, assistantDisplayName],
  );
  const groups = useMemo(
    () => filterGroupsBySearch(allGroups, searchQuery),
    [allGroups, searchQuery],
  );
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const [isNearBottom, setIsNearBottom] = useState(() => {
    if (!sessionId) return true;
    return personalScrollMemoryBySession.get(sessionId)?.atBottom ?? true;
  });
  const [newMessageCount, setNewMessageCount] = useState(0);
  const previousGroupCountRef = useRef(groups.length);
  const activeSessionRef = useRef(sessionId);
  const initialScrollAppliedRef = useRef(false);

  useEffect(() => {
    if (activeSessionRef.current === sessionId) return;
    activeSessionRef.current = sessionId;
    const restoredAtBottom = sessionId
      ? personalScrollMemoryBySession.get(sessionId)?.atBottom ?? true
      : true;
    initialScrollAppliedRef.current = false;
    previousGroupCountRef.current = groups.length;
    setIsNearBottom(restoredAtBottom);
    setNewMessageCount(0);
  }, [groups.length, sessionId]);

  const lastAssistantItemId = useMemo(() => {
    for (let gi = allGroups.length - 1; gi >= 0; gi--) {
      const group = allGroups[gi];
      for (let ii = group.items.length - 1; ii >= 0; ii--) {
        if (group.items[ii].role === 'assistant') return group.items[ii].id;
      }
    }
    return '';
  }, [allGroups]);

  const rememberScroll = useCallback((atBottom: boolean) => {
    if (!sessionId) return;
    personalScrollMemoryBySession.set(sessionId, {
      atBottom,
      groupCount: groups.length,
      updatedAt: Date.now(),
    });
    if (personalScrollMemoryBySession.size > 80) {
      const oldest = [...personalScrollMemoryBySession.entries()]
        .sort((a, b) => a[1].updatedAt - b[1].updatedAt)
        .slice(0, personalScrollMemoryBySession.size - 80);
      for (const [key] of oldest) personalScrollMemoryBySession.delete(key);
    }
  }, [groups.length, sessionId]);

  useEffect(() => {
    if (groups.length === 0) {
      initialScrollAppliedRef.current = false;
      return;
    }
    if (!isNearBottom || initialScrollAppliedRef.current) return;
    initialScrollAppliedRef.current = true;
    requestAnimationFrame(() => {
      virtuosoRef.current?.scrollToIndex({ index: 'LAST', align: 'end', behavior: 'auto' });
    });
  }, [groups.length, isNearBottom]);

  useEffect(() => {
    const previous = previousGroupCountRef.current;
    if (groups.length > previous && !isNearBottom) {
      setNewMessageCount((count) => count + groups.length - previous);
    }
    if (isNearBottom) {
      setNewMessageCount(0);
    }
    previousGroupCountRef.current = groups.length;
  }, [groups.length, isNearBottom]);

  const handleAtBottomStateChange = useCallback((atBottom: boolean) => {
    setIsNearBottom(atBottom);
    if (atBottom) setNewMessageCount(0);
    rememberScroll(atBottom);
  }, [rememberScroll]);

  const scrollToBottom = useCallback(() => {
    virtuosoRef.current?.scrollToIndex({ index: 'LAST', align: 'end', behavior: 'smooth' });
    setIsNearBottom(true);
    setNewMessageCount(0);
    rememberScroll(true);
  }, [rememberScroll]);

  const itemContent = useCallback((index: number) => {
    const group = groups[index];
    if (!group) return null;
    return (
      <PersonalGroupRow
        group={group}
        lastAssistantItemId={lastAssistantItemId}
        isRunning={isRunning}
        onRetry={onRetry}
        onOpenImage={onOpenImage}
        markdownTheme={markdownTheme}
        searchQuery={searchQuery}
        projectPath={projectPath}
      />
    );
  }, [groups, isRunning, lastAssistantItemId, markdownTheme, onOpenImage, onRetry, projectPath, searchQuery]);

  const virtuosoInitialProps = useMemo(
    () => groups.length > 0 && isNearBottom
      ? { initialTopMostItemIndex: { index: 'LAST' as const, align: 'end' as const } }
      : {},
    [groups.length, isNearBottom],
  );

  const components = useMemo(() => ({
    Header: () => <div className="h-3" />,
    EmptyPlaceholder: () => allGroups.length === 0
      ? <>{emptyPlaceholder}</>
      : (
          <div className="flex h-full items-center justify-center px-6 text-center chat-text-sm text-fg-muted">
            No matching messages.
          </div>
        ),
  }), [allGroups.length, emptyPlaceholder]);

  return (
    <div className="personal-chat-surface relative h-full min-h-0 overflow-hidden" data-testid="personal-chat-v2">
      <Virtuoso
        ref={virtuosoRef}
        className="h-full"
        data={groups}
        alignToBottom={isNearBottom}
        computeItemKey={(_index, group) => group.id}
        {...virtuosoInitialProps}
        followOutput={isNearBottom ? 'smooth' : false}
        atBottomStateChange={handleAtBottomStateChange}
        overscan={400}
        itemContent={itemContent}
        components={components}
      />
      {!isNearBottom && groups.length > 0 && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-border bg-surface-alt px-3 py-1.5 chat-text-xs text-fg shadow-lg transition-colors hover:bg-surface-hover"
          aria-label="Scroll to latest messages"
        >
          <ArrowDown className="h-3.5 w-3.5" />
          {newMessageCount > 0 ? `${newMessageCount} new message${newMessageCount === 1 ? '' : 's'}` : 'Jump to latest'}
        </button>
      )}
    </div>
  );
};
