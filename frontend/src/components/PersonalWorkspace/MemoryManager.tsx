import React, { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, Zap, Calendar } from 'lucide-react';
import { API_BASE } from '../../config';
import { cn } from '../ui/cn';

interface DiaryEntry {
  date: string;
  size: number;
  modified: string;
}

export const MemoryManager: React.FC = () => {
  const [memoryContent, setMemoryContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [diaries, setDiaries] = useState<DiaryEntry[]>([]);
  const [triggeringDream, setTriggeringDream] = useState(false);
  const [selectedDiary, setSelectedDiary] = useState<string | null>(null);
  const [diaryContent, setDiaryContent] = useState('');

  const loadMemory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/files/MEMORY.md`);
      const data = await res.json();
      setMemoryContent(data.content || '');
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDiaries = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/diaries`);
      const data = await res.json();
      setDiaries(data.diaries || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadMemory();
    loadDiaries();
  }, [loadMemory, loadDiaries]);

  const loadDiaryContent = useCallback(async (date: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/diaries/${date}`);
      const data = await res.json();
      setDiaryContent(data.content || '');
      setSelectedDiary(date);
    } catch { /* ignore */ }
  }, []);

  const triggerDream = useCallback(async () => {
    setTriggeringDream(true);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/dream/trigger`, { method: 'POST' });
      const data = await res.json();
      setTriggeringDream(false);
      loadMemory();
      window.alert(`DREAM completed. ${data.deep_sleep?.passed || 0} entries passed to MEMORY.md.`);
    } catch (err) {
      setTriggeringDream(false);
      setError(String(err));
    }
  }, [loadMemory]);

  return (
    <div className="flex flex-col h-full">
      {/* Memory section */}
      <div className="border-b border-border p-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium">MEMORY.md</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={loadMemory}
              className="p-1 rounded text-fg-muted hover:text-fg hover:bg-surface-hover"
              title="Reload"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
            <button
              type="button"
              onClick={triggerDream}
              disabled={triggeringDream}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-accent/10 text-accent hover:bg-accent/20"
            >
              {triggeringDream ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Zap className="w-3 h-3" />
              )}
              Trigger DREAM
            </button>
          </div>
        </div>
        {loading ? (
          <div className="text-xs text-fg-muted"><Loader2 className="w-3 h-3 animate-spin inline mr-1" />Loading...</div>
        ) : error ? (
          <div className="text-[11px] text-danger">{error}</div>
        ) : (
          <pre className="text-[11px] text-fg-muted font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">
            {memoryContent || '(Empty — DREAM will populate this)'}
          </pre>
        )}
      </div>

      {/* Diaries section */}
      {selectedDiary ? (
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
          <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border shrink-0">
            <button
              type="button"
              onClick={() => setSelectedDiary(null)}
              className="text-[10px] text-accent hover:underline"
            >
              ← Back
            </button>
            <span className="text-[11px] text-fg-muted">{selectedDiary}</span>
          </div>
          <pre className="flex-1 text-[11px] text-fg-muted font-mono whitespace-pre-wrap p-3 overflow-y-auto">
            {diaryContent || '(Empty)'}
          </pre>
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <Calendar className="w-3 h-3 text-fg-muted" />
            <span className="text-xs font-medium">Diaries</span>
          </div>
          {diaries.length === 0 ? (
            <div className="text-[11px] text-fg-muted text-center py-4">
              No diaries yet — sessions will auto-create them.
            </div>
          ) : (
            <div className="space-y-0.5">
              {diaries.map((d) => (
                <button
                  key={d.date}
                  type="button"
                  onClick={() => loadDiaryContent(d.date)}
                  className={cn(
                    'w-full text-left px-2 py-1 rounded text-[11px] hover:bg-surface-hover transition-colors',
                    selectedDiary === d.date ? 'bg-surface-alt text-fg' : 'text-fg-muted'
                  )}
                >
                  <span className="font-medium">{(d.date)}</span>
                  <span className="text-fg-muted ml-2">{(d.size / 1024).toFixed(1)} KB</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
