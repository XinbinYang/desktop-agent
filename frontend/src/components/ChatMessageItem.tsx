import React from 'react';
import { RotateCcw } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChatMessage, AssistantBlock, PlanState } from '../types';
import { isInternalToolName } from '../lib/internalTools';

interface ChatMessageItemProps {
  msg: ChatMessage;
  index: number;
  totalCount: number;
  lastAssistantMsgId: string | null;
  onRetry?: () => void;
  isRunning: boolean;
  expandedToolDetails: Record<string, boolean>;
  showAllToolDetails: Record<string, boolean>;
  onToggleToolDetails: (msgId: string) => void;
  onToggleShowAll: (msgId: string) => void;
  hideToolNoise: boolean;
  planState: PlanState;
  onUpdatePlanDecision: (questionId: string, selected: string[]) => void;
  onBuildPlan: () => void;
  markdownComponents: Record<string, React.FC<any>>;
  renderBlock: (block: AssistantBlock, bi: number) => React.ReactNode;
  isNoisyToolBlock: (block: Extract<AssistantBlock, { type: 'tool_call' }>) => boolean;
  ToolSummaryRow: React.FC<{
    summary: any;
    expanded: boolean;
    onToggle: () => void;
  }>;
  ReasoningBlock: React.FC<{
    text: string;
    complete?: boolean;
    startedAt?: number;
    endedAt?: number;
  }>;
}

export const ChatMessageItem: React.FC<ChatMessageItemProps> = ({
  msg,
  index,
  totalCount,
  lastAssistantMsgId,
  onRetry,
  isRunning,
  expandedToolDetails,
  showAllToolDetails,
  onToggleToolDetails,
  onToggleShowAll,
  hideToolNoise,
  planState,
  onUpdatePlanDecision,
  onBuildPlan,
  markdownComponents,
  renderBlock,
  isNoisyToolBlock,
  ToolSummaryRow,
  ReasoningBlock,
}) => {
  const isLast = index === totalCount - 1;
  const isLastAssistantMessage = msg.id === lastAssistantMsgId;

  return (
    <div className="relative pl-[var(--chat-timeline-indent)]">
      {index < totalCount - 1 && (
        <div className="absolute left-[5px] top-2.5 bottom-0 w-px bg-border-subtle" />
      )}
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
        {msg.role === 'assistant' && !msg.isTool && onRetry && !isRunning && isLastAssistantMessage && (
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
            loading="lazy"
            decoding="async"
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

        {msg.role === 'assistant' && msg.blocks && msg.blocks.length > 0 ? (
          <div className="space-y-[var(--chat-block-gap)]">
            {(() => {
              const toolBlocks = msg.blocks.filter(
                (block): block is Extract<AssistantBlock, { type: 'tool_call' }> => block.type === 'tool_call'
              ).filter((block) => !isInternalToolName(block.name));
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
                      onToggle={() => onToggleToolDetails(msg.id)}
                    />
                  )}
                  {toolBlocks.length > 0 && (isExpanded || !msg.toolSummary) && (
                    <div className="space-y-[var(--chat-block-gap)]">
                      {filteredToolBlocks.map((block, bi) => renderBlock(block, bi))}
                      {hiddenCount > 0 && (
                        <button
                          type="button"
                          onClick={() => onToggleShowAll(msg.id)}
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
          <>
            <ReasoningBlock text={msg.reasoning} complete />
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
  );
};
