import React, { useRef, useEffect } from 'react';

interface TerminalOutputProps {
  content: string;
}

export const TerminalOutput: React.FC<TerminalOutputProps> = ({ content }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [content]);

  if (!content) {
    return (
      <div className="h-full flex items-center justify-center text-fg-muted text-sm">
        暂无终端输出
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-app p-3">
      <pre className="text-xs font-mono text-fg-secondary whitespace-pre-wrap leading-relaxed">
        {content}
      </pre>
      <div ref={bottomRef} />
    </div>
  );
};
