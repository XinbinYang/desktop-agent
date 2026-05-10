import React, { useRef, useEffect } from 'react';
import { TerminalSquare, Copy, Trash2 } from 'lucide-react';

interface TerminalPanelProps {
  logs: string[];
}

export const TerminalPanel: React.FC<TerminalPanelProps> = ({ logs }) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const copyAll = () => {
    navigator.clipboard.writeText(logs.join('\n'));
  };

  return (
    <div className="h-full flex flex-col bg-app">
      <div className="flex items-center justify-between px-3 py-1.5 bg-surface border-b border-border">
        <div className="flex items-center gap-1.5">
          <TerminalSquare className="w-3.5 h-3.5 text-fg-secondary" />
          <span className="text-xs font-medium text-fg-secondary">执行日志</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={copyAll} className="p-1 text-fg-muted hover:text-fg-secondary" title="复制全部">
            <Copy className="w-3 h-3" />
          </button>
        </div>
      </div>
      
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-2 font-mono text-xs">
        {logs.map((log, i) => (
          <div key={i} className="text-fg-secondary leading-relaxed py-0.5 border-b border-border-subtle/50">
            {log}
          </div>
        ))}
        {logs.length === 0 && (
          <div className="text-fg-muted italic text-center mt-4">等待执行...</div>
        )}
      </div>
    </div>
  );
};