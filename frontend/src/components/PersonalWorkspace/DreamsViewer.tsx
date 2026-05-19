import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, Moon } from 'lucide-react';
import { API_BASE } from '../../config';

export const DreamsViewer: React.FC = () => {
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDreams = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/dreams`);
      const data = await res.json();
      setContent(data.content || '');
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDreams(); }, [loadDreams]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-1.5">
          <Moon className="w-3.5 h-3.5 text-fg-muted" />
          <span className="text-xs font-medium">DREAMS.md</span>
        </div>
        <button
          type="button"
          onClick={loadDreams}
          className="p-1 rounded text-fg-muted hover:text-fg hover:bg-surface-hover"
          title="Reload"
        >
          <RefreshCw className="w-3 h-3" />
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-3">
        {loading ? (
          <div className="text-xs text-fg-muted"><Loader2 className="w-3 h-3 animate-spin inline mr-1" />Loading...</div>
        ) : error ? (
          <div className="text-[11px] text-danger">{error}</div>
        ) : content ? (
          <pre className="text-[11px] text-fg-muted font-mono whitespace-pre-wrap">{content}</pre>
        ) : (
          <div className="text-xs text-fg-muted text-center py-8">
            <Moon className="w-6 h-6 mx-auto mb-2 opacity-30" />
            <p>No dreams yet.</p>
            <p className="text-[10px] mt-1">DREAM consolidation runs automatically after enough sessions accumulate.</p>
          </div>
        )}
      </div>
    </div>
  );
};
