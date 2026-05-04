import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Wrench, Bot, CheckCircle2, XCircle, AlertCircle } from 'lucide-react';
import { ToolCall, WorkerEvent } from '../types';
import { JsonTree } from './JsonTree';

interface ToolCallViewProps {
  toolCall: ToolCall;
}

const WorkerCard: React.FC<{ events: WorkerEvent[] }> = ({ events }) => {
  const [expanded, setExpanded] = useState(true);

  const doneEvent = events.find(e => e.type === 'worker_done');
  const status = doneEvent?.status || 'running';
  const statusIcon = status === 'completed' ? <CheckCircle2 className="w-3 h-3 text-green-400" />
    : status === 'failed' || status === 'cancelled' ? <XCircle className="w-3 h-3 text-red-400" />
    : status === 'max_iterations_reached' ? <AlertCircle className="w-3 h-3 text-yellow-400" />
    : <Bot className="w-3 h-3 text-blue-400 animate-pulse" />;

  const toolEvents = events.filter(e => e.type === 'worker_tool_call');

  return (
    <div className="border border-gray-700 rounded mt-2 bg-gray-900/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-xs hover:bg-gray-800/50 rounded-t"
      >
        {statusIcon}
        <span className="text-gray-300">Worker: {doneEvent?.workerId || events[0]?.workerId}</span>
        {doneEvent?.durationMs != null && (
          <span className="text-gray-500 text-[10px]">{doneEvent.durationMs}ms</span>
        )}
        <span className="text-gray-500 text-[10px] ml-auto">
          {status === 'completed' ? 'Done' : status}
        </span>
        {expanded ? <ChevronDown className="w-3 h-3 text-gray-600" /> : <ChevronRight className="w-3 h-3 text-gray-600" />}
      </button>
      {expanded && (
        <div className="px-2 pb-2 space-y-1">
          {toolEvents.map((te, i) => (
            <div key={i} className="text-[10px] text-gray-400 pl-4 border-l border-gray-700/50">
              <span className="text-blue-400">{te.toolName}</span>
              {te.toolDurationMs != null && (
                <span className="text-gray-600 ml-1">{te.toolDurationMs}ms</span>
              )}
              <span className="text-gray-500 ml-1 truncate block">
                {te.toolResult?.slice(0, 120)}
              </span>
            </div>
          ))}
          {doneEvent?.result && (
            <div className="text-[10px] text-gray-300 mt-1 pl-2 border-l-2 border-green-700/50">
              {doneEvent.result.slice(0, 300)}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export const ToolCallView: React.FC<ToolCallViewProps> = ({ toolCall }) => {
  const [expanded, setExpanded] = useState(false);

  const isError = toolCall.result.startsWith('[ERROR]');
  const isDispatch = toolCall.name === 'dispatch_worker' || toolCall.name === 'dispatch_parallel';
  const hasWorkerEvents = toolCall.workerEvents && toolCall.workerEvents.length > 0;

  // Group worker events by workerId
  const workerGroups: Record<string, WorkerEvent[]> = {};
  if (hasWorkerEvents) {
    for (const we of toolCall.workerEvents!) {
      if (!workerGroups[we.workerId]) workerGroups[we.workerId] = [];
      workerGroups[we.workerId].push(we);
    }
  }

  return (
    <div className="tool-call-box">
      <button
        onClick={() => setExpanded(!expanded)}
        className="tool-call-header w-full text-left"
        aria-label={expanded ? '折叠工具调用详情' : '展开工具调用详情'}
      >
        <Wrench className="w-3 h-3" />
        <span className="flex-1">{toolCall.name}</span>
        {typeof toolCall.durationMs === 'number' && (
          <span className="text-gray-500 text-[10px]">{toolCall.durationMs}ms</span>
        )}
        {isError ? (
          <span className="text-red-400 text-[10px]">失败</span>
        ) : isDispatch && hasWorkerEvents ? (
          <span className="text-blue-400 text-[10px]">
            {Object.keys(workerGroups).length} worker(s)
          </span>
        ) : (
          <span className="text-green-400 text-[10px]">成功</span>
        )}
        {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
      </button>

      {expanded && (
        <div className="px-3 py-2 space-y-2 text-xs">
          {(toolCall.runId || toolCall.toolCallId) && (
            <div className="text-[10px] text-gray-500 space-y-0.5">
              {toolCall.runId && <div>Run: {toolCall.runId}</div>}
              {toolCall.toolCallId && <div>Call: {toolCall.toolCallId}</div>}
            </div>
          )}
          <div>
            <div className="text-gray-500 mb-0.5">参数:</div>
            <div className="bg-gray-950 rounded p-1.5 font-mono overflow-x-auto">
              <JsonTree data={toolCall.args} />
            </div>
          </div>

          {isDispatch && hasWorkerEvents && (
            <div>
              <div className="text-gray-500 mb-0.5">Worker 执行:</div>
              {Object.entries(workerGroups).map(([workerId, evts]) => (
                <WorkerCard key={workerId} events={evts} />
              ))}
            </div>
          )}

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
