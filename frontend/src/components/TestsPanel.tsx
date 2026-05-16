import React, { useState, useEffect, useCallback } from 'react';
import { Play, RotateCcw, Check, X, SkipForward, AlertTriangle, Loader, FileText } from 'lucide-react';
import { API_BASE, withAuthQuery } from '../config';

interface TestResultItem {
  name: string;
  status: 'passed' | 'failed' | 'skipped' | 'error';
  duration_ms: number;
  file_path: string;
}

interface TestRunData {
  run_id: string | null;
  framework: string | null;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  errors: number;
  duration_ms: number;
  results: TestResultItem[];
}

interface TestsPanelProps {
  onOpenFile?: (path: string) => void;
}

export const TestsPanel: React.FC<TestsPanelProps> = ({ onOpenFile }) => {
  const [run, setRun] = useState<TestRunData | null>(null);
  const [running, setRunning] = useState(false);
  const [filter, setFilter] = useState('');
  const [framework, setFramework] = useState<string | null>(null);

  // Load framework detection on mount
  useEffect(() => {
    fetch(withAuthQuery(`${API_BASE}/api/tests/framework`))
      .then((r) => r.json())
      .then((d) => setFramework(d.framework))
      .catch(() => {});
  }, []);

  // Load last run on mount
  useEffect(() => {
    fetch(withAuthQuery(`${API_BASE}/api/tests/last`))
      .then((r) => r.json())
      .then((d) => {
        if (d.run_id) setRun(d);
      })
      .catch(() => {});
  }, []);

  const runTests = useCallback(async () => {
    setRunning(true);
    try {
      const params = new URLSearchParams();
      if (filter) params.set('filter', filter);
      const url = withAuthQuery(`${API_BASE}/api/tests/run?${params.toString()}`);
      const res = await fetch(url, { method: 'POST' });
      const data = await res.json();
      if (data.run_id) setRun(data);
    } catch (e) {
      console.error('Test run failed:', e);
    } finally {
      setRunning(false);
    }
  }, [filter]);

  const statusIcon = (status: string) => {
    switch (status) {
      case 'passed': return <Check className="w-3 h-3 text-green-400" />;
      case 'failed': return <X className="w-3 h-3 text-red-400" />;
      case 'error': return <AlertTriangle className="w-3 h-3 text-red-400" />;
      case 'skipped': return <SkipForward className="w-3 h-3 text-fg-muted" />;
      default: return null;
    }
  };

  if (!framework) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-xs text-fg-muted p-4">
        <FileText className="w-8 h-8 opacity-30" />
        <p>当前项目未检测到测试框架</p>
        <p className="text-[10px]">支持 pytest / vitest / jest</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-app">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-surface/30">
        <span className="text-[10px] text-fg-muted uppercase tracking-wider">{framework}</span>
        <div className="flex-1" />
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && runTests()}
          placeholder="过滤..."
          className="w-32 px-2 py-0.5 rounded text-[10px] bg-surface-input border border-border text-fg outline-none focus:border-accent"
        />
        <button
          type="button"
          onClick={runTests}
          disabled={running}
          className="flex items-center gap-1 px-2.5 py-1 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20 transition-colors disabled:opacity-50"
        >
          {running ? <Loader className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
          运行
        </button>
      </div>

      {/* Summary bar */}
      {run && run.total > 0 && (
        <div className="flex items-center gap-3 px-3 py-1.5 border-b border-border bg-surface/20 text-[10px]">
          <span className="text-fg-muted">{run.total} tests</span>
          {run.passed > 0 && <span className="text-green-400">{run.passed} passed</span>}
          {run.failed > 0 && <span className="text-red-400">{run.failed} failed</span>}
          {run.skipped > 0 && <span className="text-fg-muted">{run.skipped} skipped</span>}
          {run.errors > 0 && <span className="text-red-400">{run.errors} errors</span>}
          <span className="text-fg-muted ml-auto">{run.duration_ms}ms</span>
        </div>
      )}

      {/* Results list */}
      <div className="flex-1 overflow-y-auto">
        {run?.results.map((r, i) => (
          <div
            key={i}
            className={`flex items-center gap-2 px-3 py-1.5 border-b border-border/30 hover:bg-surface/30 transition-colors ${
              r.status === 'failed' || r.status === 'error' ? 'bg-red-500/5' : ''
            }`}
          >
            {statusIcon(r.status)}
            <span className="text-xs text-fg truncate flex-1">{r.name}</span>
            {r.duration_ms > 0 && (
              <span className="text-[10px] text-fg-muted shrink-0">{r.duration_ms}ms</span>
            )}
            {r.file_path && onOpenFile && (
              <button
                type="button"
                onClick={() => onOpenFile(r.file_path)}
                className="text-[10px] text-blue-300 hover:text-blue-200 shrink-0"
              >
                <FileText className="w-3 h-3" />
              </button>
            )}
          </div>
        ))}
        {(!run || run.total === 0) && !running && (
          <div className="flex flex-col items-center justify-center gap-2 p-8 text-xs text-fg-muted">
            <RotateCcw className="w-6 h-6 opacity-30" />
            <p>{run ? 'No tests found' : '点击运行按钮执行测试'}</p>
          </div>
        )}
      </div>
    </div>
  );
};
