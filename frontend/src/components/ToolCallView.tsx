import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Wrench } from 'lucide-react';
import { ToolCall } from '../types';

interface ToolCallViewProps {
  toolCall: ToolCall;
}

export const ToolCallView: React.FC<ToolCallViewProps> = ({ toolCall }) => {
  const [expanded, setExpanded] = useState(false);

  const isError = toolCall.result.startsWith('[ERROR]');

  return (
    <div className="tool-call-box">
      <button
        onClick={() => setExpanded(!expanded)}
        className="tool-call-header w-full text-left"
      >
        <Wrench className="w-3 h-3" />
        <span className="flex-1">{toolCall.name}</span>
        {isError ? (
          <span className="text-red-400 text-[10px]">失败</span>
        ) : (
          <span className="text-green-400 text-[10px]">成功</span>
        )}
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
      </button>
      
      {expanded && (
        <div className="px-3 py-2 space-y-2 text-xs">
          <div>
            <div className="text-gray-500 mb-0.5">参数:</div>
            <div className="bg-gray-950 rounded p-1.5 font-mono text-gray-400 overflow-x-auto">
              {JSON.stringify(toolCall.args, null, 2)}
            </div>
          </div>
          <div>
            <div className="text-gray-500 mb-0.5">结果:</div>
            <div className={`bg-gray-950 rounded p-1.5 font-mono whitespace-pre-wrap ${isError ? 'text-red-400' : 'text-gray-300'}`}>
              {toolCall.result}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};