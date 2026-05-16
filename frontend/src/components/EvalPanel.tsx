import React, { useState, useEffect, useCallback } from 'react';
import { Play, Check, X, RotateCcw, AlertTriangle, Loader, Clock, GitBranch, FileText } from 'lucide-react';
import { API_BASE, withAuthQuery } from '../config';

interface EvalTask {
  id: string;
  category: string;
  prompt: string;
  verification: string;
}

interface EvalResultItem {
  task_id: string;
  passed: boolean;
  iterations: number;
  tool_calls: number;
  duration_ms: number;
  files_changed: string[];
  verification_output: string;
  verification_exit_code: number;
  error: string;
}

interface EvalRunData {
  run_id: string | null;
  status: string;
  total_tasks?: number;
  completed_tasks?: number;
  success_rate?: number | null;
  results?: EvalResultItem[];
  tasks?: EvalTask[];
}

export const EvalPanel: React.FC = () => {
  const [tasks, setTasks] = useState<EvalTask[]>([]);
  const [running, setRunning] = useState(false);
  const [runData, setRunData] = useState<EvalRunData | null>(null);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);

  // Load tasks on mount
  useEffect(() => {
    fetch(withAuthQuery(`${API_BASE}/api/agent/evals/tasks`))
      .then((r) => r.json())
      .then((d) => {
        if (d.tasks) setTasks(d.tasks);
      })
      .catch(() => {});
  }, []);

  // Load last results
  useEffect(() => {
    fetch(withAuthQuery(`${API_BASE}/api/agent/evals/results`))
      .then((r) => r.json())
      .then((d) => setRunData(d))
      .catch(() => {});
  }, []);

  const runAll = useCallback(async () => {
    setRunning(true);
    try {
      const res = await fetch(`${API_BASE}/api/agent/evals/run`, { method: 'POST' });
      const data = await res.json();
      setRunData(data);
    } catch (e) {
      console.error('Eval run failed:', e);
    } finally {
      setRunning(false);
    }
  }, []);

  const runOne = useCallback(async (taskId: string) => {
    setRunning(true);
    try {
      const res = await fetch(`${API_BASE}/api/agent/evals/run?task_id=${taskId}`, { method: 'POST' });
      const data = await res.json();
      setRunData(data);
    } catch (e) {
      console.error('Eval run failed:', e);
    } finally {
      setRunning(false);
    }
  }, []);

  const hasRun = runData?.run_id != null && (runData?.results?.length || 0) > 0;
  const results = runData?.results || [];
  const resultMap: Record<string, EvalResultItem> = {};
  results.forEach((r) => { resultMap[r.task_id] = r; });

  if (tasks.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-xs text-fg-muted p-4">
        <FileText className="w-8 h-8 opacity-30" />
        <p>未找到 eval manifest</p>
        <p className="text-[10px]">在项目根目录放置 agent_evals/manifest.json</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-app">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-surface/30">
        <span className="text-[10px] text-fg-muted uppercase tracking-wider">
          Eval ({tasks.length} tasks)
        </span>
        <div className="flex-1" />
        {hasRun && (
          <span className="text-[10px] text-fg-muted">
            {runData!.success_rate != null
              ? `${(runData!.success_rate! * 100).toFixed(0)}% passed`
              : 'No results'}
          </span>
        )}
        <button
          type="button"
          onClick={runAll}
          disabled={running}
          className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20 transition-colors disabled:opacity-50"
        >
          {running ? <Loader className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
          Run All
        </button>
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto">
        {tasks.map((task) => {
          const result = resultMap[task.id];
          const isSelected = selectedTask === task.id;
          return (
            <div key={task.id}>
              <button
                type="button"
                onClick={() => setSelectedTask(isSelected ? null : task.id)}
                className={`w-full flex items-center gap-2 px-3 py-2 text-left border-b border-border/20 hover:bg-surface/20 transition-colors ${
                  isSelected ? 'bg-surface/30' : ''
                }`}
              >
                <span className="shrink-0">
                  {result ? (
                    result.passed
                      ? <Check className="w-3.5 h-3.5 text-green-400" />
                      : <X className="w-3.5 h-3.5 text-red-400" />
                  ) : (
                    <Clock className="w-3.5 h-3.5 text-fg-muted" />
                  )}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-fg truncate">{task.id}</div>
                  <div className="text-[10px] text-fg-muted">{task.category}</div>
                </div>
                {result && (
                  <div className="flex items-center gap-2 text-[10px] text-fg-muted shrink-0">
                    <span>{result.iterations} iters</span>
                    <span>{result.tool_calls} tools</span>
                    <span>{(result.duration_ms / 1000).toFixed(1)}s</span>
                  </div>
                )}
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); runOne(task.id); }}
                  disabled={running}
                  className="shrink-0 p-1 rounded text-fg-muted hover:text-accent hover:bg-accent/10 transition-colors disabled:opacity-50"
                  title="Run this task"
                >
                  <Play className="w-3 h-3" />
                </button>
              </button>

              {/* Expanded detail */}
              {isSelected && (
                <div className="px-3 py-2 bg-surface/10 border-b border-border/20 text-xs space-y-2">
                  <div>
                    <span className="text-fg-muted">Prompt: </span>
                    <span className="text-fg">{task.prompt}</span>
                  </div>
                  <div>
                    <span className="text-fg-muted">Verification: </span>
                    <code className="text-[10px] bg-surface-alt px-1 py-0.5 rounded">{task.verification}</code>
                  </div>
                  {result && (
                    <>
                      <div className="flex gap-3">
                        <span className="text-fg-muted">
                          Status: <span className={result.passed ? 'text-green-400' : 'text-red-400'}>
                            {result.passed ? 'PASSED' : 'FAILED'}
                          </span>
                        </span>
                        <span className="text-fg-muted">Exit: {result.verification_exit_code}</span>
                      </div>
                      {result.error && (
                        <div className="text-red-400 bg-red-500/5 p-2 rounded">{result.error}</div>
                      )}
                      {result.files_changed.length > 0 && (
                        <div className="text-fg-muted">
                          Files: {result.files_changed.join(', ')}
                        </div>
                      )}
                      {result.verification_output && (
                        <pre className="text-[10px] bg-surface-alt p-2 rounded max-h-40 overflow-auto whitespace-pre-wrap text-fg-secondary">
                          {result.verification_output}
                        </pre>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-3 px-3 py-1 border-t border-border bg-surface/20 text-[10px] text-fg-muted">
        <span>{tasks.length} tasks</span>
        {hasRun && (
          <>
            <span className="text-green-400">{results.filter((r) => r.passed).length} passed</span>
            <span className="text-red-400">{results.filter((r) => !r.passed).length} failed</span>
          </>
        )}
        {runData?.status === 'not_run' && <span>尚未运行</span>}
      </div>
    </div>
  );
};
