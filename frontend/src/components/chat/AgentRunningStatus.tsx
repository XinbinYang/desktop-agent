import React from 'react';
import { Loader2 } from 'lucide-react';

interface AgentRunningSpinnerProps {
  className?: string;
  testId?: string;
}

interface AgentRunningStatusProps {
  label?: string;
  className?: string;
  iconClassName?: string;
  textClassName?: string;
  testId?: string;
}

export const AgentRunningSpinner: React.FC<AgentRunningSpinnerProps> = ({
  className = '',
  testId = 'agent-running-spinner',
}) => {
  const iconClassName = className.trim() || 'h-3 w-3';
  return (
    <span
      className={['agent-running-spinner inline-flex shrink-0 animate-spin', iconClassName].filter(Boolean).join(' ')}
      data-testid={testId}
      aria-hidden
    >
      <Loader2 className="block h-full w-full" />
    </span>
  );
};

export const AgentRunningStatus: React.FC<AgentRunningStatusProps> = ({
  label = 'Desktop Agent is thinking...',
  className = '',
  iconClassName = '',
  textClassName = '',
  testId = 'agent-running-status',
}) => (
  <div
    className={['inline-flex items-center gap-1.5', className].filter(Boolean).join(' ')}
    role="status"
    aria-live="polite"
    data-testid={testId}
  >
    <AgentRunningSpinner className={iconClassName} />
    <span className={textClassName}>{label}</span>
  </div>
);
