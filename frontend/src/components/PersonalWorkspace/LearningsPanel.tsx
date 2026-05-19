import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, AlertTriangle, Lightbulb, Wrench } from 'lucide-react';
import { API_BASE } from '../../config';
import { cn } from '../ui/cn';

interface LearningsData {
  learnings?: string;
  errors?: string;
  feature_requests?: string;
  promotable?: Array<{ discovery: string; recurrence: number }>;
}

export const LearningsPanel: React.FC = () => {
  const [data, setData] = useState<LearningsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<'learnings' | 'errors' | 'features'>('learnings');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/learnings`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const sections = [
    { id: 'learnings' as const, label: 'Discoveries', icon: Lightbulb, key: 'learnings' as const },
    { id: 'errors' as const, label: 'Errors', icon: AlertTriangle, key: 'errors' as const },
    { id: 'features' as const, label: 'Requests', icon: Wrench, key: 'feature_requests' as const },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Sub-tabs */}
      <div className="flex border-b border-border shrink-0">
        {sections.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setActiveSection(s.id)}
            className={cn(
              'flex items-center gap-1 px-3 py-1.5 text-[11px] border-b-2 -mb-px transition-colors',
              activeSection === s.id
                ? 'border-accent text-fg'
                : 'border-transparent text-fg-muted hover:text-fg-secondary'
            )}
          >
            <s.icon className="w-3 h-3" />
            {s.label}
          </button>
        ))}
        <div className="flex-1" />
        <button
          type="button"
          onClick={load}
          className="px-2 text-fg-muted hover:text-fg"
          title="Reload"
        >
          <RefreshCw className="w-3 h-3" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3">
        {loading ? (
          <div className="text-xs text-fg-muted"><Loader2 className="w-3 h-3 animate-spin inline mr-1" />Loading...</div>
        ) : error ? (
          <div className="text-[11px] text-danger">{error}</div>
        ) : data ? (
          <>
            {/* Promotable learnings banner */}
            {data.promotable && data.promotable.length > 0 && (
              <div className="mb-3 p-2 rounded bg-yellow-500/10 border border-yellow-500/20">
                <div className="text-[10px] font-medium text-yellow-400 mb-1">Ready for promotion to SOUL</div>
                {data.promotable.map((p, i) => (
                  <div key={i} className="text-[10px] text-fg-muted">
                    {p.discovery} (recurrence: {p.recurrence})
                  </div>
                ))}
              </div>
            )}
            <pre className="text-[11px] text-fg-muted font-mono whitespace-pre-wrap">
              {(data as any)[sections.find((s) => s.id === activeSection)!.key] || '(Empty)'}
            </pre>
          </>
        ) : null}
      </div>
    </div>
  );
};
