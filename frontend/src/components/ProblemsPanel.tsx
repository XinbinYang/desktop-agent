import React, { useState, useEffect, useCallback } from 'react';
import { AlertCircle, AlertTriangle, Info, Play, RefreshCw, Filter, FileText } from 'lucide-react';
import { API_BASE, withAuthQuery } from '../config';

interface ProblemItem {
  file_path: string;
  line: number;
  column: number;
  severity: 'error' | 'warning' | 'info';
  message: string;
  source: string;
}

interface ProblemsPanelProps {
  onOpenFile?: (path: string, line?: number) => void;
}

export const ProblemsPanel: React.FC<ProblemsPanelProps> = ({ onOpenFile }) => {
  const [problems, setProblems] = useState<ProblemItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [sources, setSources] = useState<string[]>([]);
  const [filterSource, setFilterSource] = useState('');
  const [filterSeverity, setFilterSeverity] = useState('');
  const [lastSource, setLastSource] = useState('');

  // Detect available linters
  useEffect(() => {
    fetch(withAuthQuery(`${API_BASE}/api/diagnostics/linters`))
      .then((r) => r.json())
      .then((d) => setSources(d.linters || []))
      .catch(() => {});
  }, []);

  // Load last results
  useEffect(() => {
    fetch(withAuthQuery(`${API_BASE}/api/diagnostics/last`))
      .then((r) => r.json())
      .then((d) => {
        if (d.items?.length) {
          setProblems(d.items);
          setLastSource(d.source || '');
        }
      })
      .catch(() => {});
  }, []);

  const runAll = useCallback(async () => {
    setLoading(true);
    const allProblems: ProblemItem[] = [];
    for (const src of sources) {
      try {
        const url = withAuthQuery(`${API_BASE}/api/diagnostics/run?source=${src}`);
        const res = await fetch(url, { method: 'POST' });
        const data = await res.json();
        for (const r of data.results || []) {
          allProblems.push(...(r.items || []));
        }
      } catch (e) {
        console.error(`Diagnostics ${src} failed:`, e);
      }
    }
    setProblems(allProblems);
    setLoading(false);
  }, [sources]);

  const filtered = problems.filter((p) => {
    if (filterSource && p.source !== filterSource) return false;
    if (filterSeverity && p.severity !== filterSeverity) return false;
    return true;
  });

  const errors = filtered.filter((p) => p.severity === 'error').length;
  const warnings = filtered.filter((p) => p.severity === 'warning').length;
  const infos = filtered.filter((p) => p.severity === 'info').length;

  const severityIcon = (s: string) => {
    switch (s) {
      case 'error': return <AlertCircle className="w-3 h-3 text-red-400" />;
      case 'warning': return <AlertTriangle className="w-3 h-3 text-yellow-400" />;
      case 'info': return <Info className="w-3 h-3 text-blue-400" />;
      default: return null;
    }
  };

  if (sources.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 text-xs text-fg-muted p-4">
        <AlertCircle className="w-8 h-8 opacity-30" />
        <p>当前项目未检测到 linter/typechecker</p>
        <p className="text-[10px]">支持 mypy / pyright / tsc / eslint</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-app">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-surface/30">
        <span className="text-[10px] text-fg-muted uppercase tracking-wider">Problems</span>
        <div className="flex gap-1 ml-2">
          {sources.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setFilterSource(filterSource === s ? '' : s)}
              className={`px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors ${
                filterSource === s
                  ? 'bg-accent/10 text-accent'
                  : 'bg-surface-alt text-fg-muted hover:text-fg'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-1 text-[10px]">
          <button
            type="button"
            onClick={() => setFilterSeverity(filterSeverity === 'error' ? '' : 'error')}
            className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded transition-colors ${
              filterSeverity === 'error' ? 'bg-red-500/10 text-red-400' : 'text-fg-muted hover:text-fg'
            }`}
          >
            <AlertCircle className="w-3 h-3" />{errors}
          </button>
          <button
            type="button"
            onClick={() => setFilterSeverity(filterSeverity === 'warning' ? '' : 'warning')}
            className={`flex items-center gap-0.5 px-1.5 py-0.5 rounded transition-colors ${
              filterSeverity === 'warning' ? 'bg-yellow-500/10 text-yellow-400' : 'text-fg-muted hover:text-fg'
            }`}
          >
            <AlertTriangle className="w-3 h-3" />{warnings}
          </button>
        </div>
        <button
          type="button"
          onClick={runAll}
          disabled={loading}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20 transition-colors disabled:opacity-50 ml-1"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          运行
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {filtered.map((p, i) => (
          <div
            key={i}
            className={`flex items-start gap-2 px-3 py-1.5 border-b border-border/20 hover:bg-surface/20 transition-colors cursor-pointer ${
              p.severity === 'error' ? 'bg-red-500/[0.02]' : ''
            }`}
            onClick={() => onOpenFile?.(p.file_path, p.line)}
          >
            <span className="mt-0.5 shrink-0">{severityIcon(p.severity)}</span>
            <div className="flex-1 min-w-0">
              <span className="text-xs text-fg">{p.message}</span>
              <div className="flex items-center gap-2 mt-0.5 text-[10px] text-fg-muted">
                <span className="font-mono">{p.file_path}:{p.line}</span>
                <span className="px-1 py-0.5 rounded bg-surface-alt text-fg-muted">
                  {p.source}
                </span>
              </div>
            </div>
            {onOpenFile && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onOpenFile(p.file_path, p.line); }}
                className="shrink-0 mt-0.5 text-fg-muted hover:text-fg"
              >
                <FileText className="w-3 h-3" />
              </button>
            )}
          </div>
        ))}
        {filtered.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center gap-2 p-8 text-xs text-fg-muted">
            <Info className="w-6 h-6 opacity-30" />
            <p>{problems.length === 0 ? '点击运行按钮检查代码' : '没有匹配的问题'}</p>
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-3 px-3 py-1 border-t border-border bg-surface/20 text-[10px] text-fg-muted">
        <span className="text-red-400">{errors} errors</span>
        <span className="text-yellow-400">{warnings} warnings</span>
        <span className="text-blue-400">{infos} info</span>
        <span className="ml-auto">{filtered.length} total</span>
      </div>
    </div>
  );
};
