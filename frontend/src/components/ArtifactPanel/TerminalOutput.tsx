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
      <div className="h-full flex items-center justify-center text-gray-500 text-sm">
        暂无终端输出
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-gray-950 p-3">
      <pre className="text-xs font-mono text-gray-300 whitespace-pre-wrap leading-relaxed">
        {content}
      </pre>
      <div ref={bottomRef} />
    </div>
  );
};
