import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ArrowDown,
  ArrowUp,
  Calendar,
  ChevronDown,
  ChevronRight,
  Database,
  Layers,
  Loader2,
  RefreshCw,
  Save,
  Search,
  Trash2,
  Zap,
} from 'lucide-react';
import { API_BASE } from '../../config';
import { cn } from '../ui/cn';

type MemoryType = 'working' | 'episodic' | 'semantic' | 'procedural' | 'identity';
type MemoryTier = 'hot' | 'warm' | 'cold' | 'archived';

interface MemoryItem {
  id: string;
  memory_type: MemoryType;
  content: string;
  summary: string;
  source: string;
  source_ref: string;
  scope: string;
  tier: MemoryTier;
  confidence: number;
  created_by: string;
  created_at: number;
  updated_at: number;
  last_verified_at: number;
  metadata: Record<string, unknown>;
  score: number;
  deleted_at?: number | null;
}

interface MemoryStatus {
  status: string;
  total_items: number;
  counts_by_type: Partial<Record<MemoryType, number>>;
  counts_by_tier: Partial<Record<MemoryTier, number>>;
  pending_candidates: number;
  vector_available: boolean;
  vector_error?: string;
  embedding_model?: string;
  db_size_mb?: number;
}

interface DiaryEntry {
  date: string;
  size: number;
  modified: string;
}

interface MemoryManagerProps {
  focusSignal?: number;
}

const MEMORY_TYPES: { id: '' | MemoryType; label: string }[] = [
  { id: '', label: 'All' },
  { id: 'working', label: 'Working' },
  { id: 'episodic', label: 'Episodic' },
  { id: 'semantic', label: 'Semantic' },
  { id: 'procedural', label: 'Procedural' },
  { id: 'identity', label: 'Identity' },
];

const TIERS: { id: '' | MemoryTier; label: string }[] = [
  { id: '', label: 'Any tier' },
  { id: 'hot', label: 'Hot' },
  { id: 'warm', label: 'Warm' },
  { id: 'cold', label: 'Cold' },
  { id: 'archived', label: 'Archived' },
];

const tierOrder: MemoryTier[] = ['hot', 'warm', 'cold', 'archived'];

function formatTime(value?: number | string): string {
  if (!value) return 'Never';
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown';
  return date.toLocaleString();
}

function tierClass(tier: MemoryTier): string {
  if (tier === 'hot') return 'text-danger';
  if (tier === 'warm') return 'text-accent';
  if (tier === 'cold') return 'text-fg-muted';
  return 'text-fg-secondary';
}

export const MemoryManager: React.FC<MemoryManagerProps> = ({ focusSignal = 0 }) => {
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState('');
  const [memoryType, setMemoryType] = useState<'' | MemoryType>('');
  const [tier, setTier] = useState<'' | MemoryTier>('');
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [selected, setSelected] = useState<MemoryItem | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editType, setEditType] = useState<MemoryType>('episodic');
  const [editTier, setEditTier] = useState<MemoryTier>('warm');
  const [memoryContent, setMemoryContent] = useState('');
  const [diaries, setDiaries] = useState<DiaryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [triggeringDream, setTriggeringDream] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memoryOsUnavailable, setMemoryOsUnavailable] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const fallbackStatus = useCallback((message: string) => {
    setMemoryOsUnavailable(message);
    setStatus({
      status: 'unavailable',
      total_items: 0,
      counts_by_type: {},
      counts_by_tier: {},
      pending_candidates: 0,
      vector_available: false,
      vector_error: message,
    });
    setItems([]);
    setSelected(null);
  }, []);

  const loadStatus = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/agents/personal/memory/status`);
    if (res.status === 404) {
      fallbackStatus('Memory OS API is not available from the running backend. Restart the Desktop Agent backend to enable the new index.');
      return;
    }
    if (!res.ok) throw new Error(`Memory status failed: ${res.status}`);
    setMemoryOsUnavailable(null);
    setStatus(await res.json());
  }, [fallbackStatus]);

  const runSearch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/memory/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          memory_type: memoryType,
          tier,
          limit: 50,
        }),
      });
      if (res.status === 404) {
        fallbackStatus('Memory OS API is not available from the running backend. Restart the Desktop Agent backend to enable search.');
        return;
      }
      if (!res.ok) throw new Error(`Memory search failed: ${res.status}`);
      setMemoryOsUnavailable(null);
      const data = await res.json();
      const nextItems: MemoryItem[] = data.items || [];
      setItems(nextItems);
      setSelected((current) => {
        if (!current) return nextItems[0] || null;
        return nextItems.find((item) => item.id === current.id) || nextItems[0] || null;
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [memoryType, query, tier]);

  const loadLegacyMemory = useCallback(async () => {
    try {
      const [memoryRes, diariesRes] = await Promise.all([
        fetch(`${API_BASE}/api/agents/personal/files/MEMORY.md`),
        fetch(`${API_BASE}/api/agents/personal/diaries`),
      ]);
      const memoryData = await memoryRes.json();
      const diariesData = await diariesRes.json();
      setMemoryContent(memoryData.content || '');
      setDiaries(diariesData.diaries || []);
    } catch {
      // Memory OS is the primary surface; legacy panes are best-effort.
    }
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      await Promise.all([loadStatus(), runSearch(), loadLegacyMemory()]);
    } catch (err) {
      setError(String(err));
    }
  }, [loadLegacyMemory, loadStatus, runSearch]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    if (focusSignal) {
      window.setTimeout(() => searchInputRef.current?.focus(), 0);
    }
  }, [focusSignal]);

  useEffect(() => {
    if (!selected) {
      setEditContent('');
      return;
    }
    setEditContent(selected.content);
    setEditType(selected.memory_type);
    setEditTier(selected.tier);
  }, [selected]);

  const rebuild = useCallback(async () => {
    setRebuilding(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/memory/rebuild`, { method: 'POST' });
      if (res.status === 404) {
        fallbackStatus('Memory OS API is not available from the running backend. Restart the Desktop Agent backend before rebuilding.');
        return;
      }
      if (!res.ok) throw new Error(`Rebuild failed: ${res.status}`);
      await refreshAll();
    } catch (err) {
      setError(String(err));
    } finally {
      setRebuilding(false);
    }
  }, [refreshAll]);

  const triggerDream = useCallback(async () => {
    setTriggeringDream(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/dream/trigger`, { method: 'POST' });
      if (!res.ok) throw new Error(`DREAM failed: ${res.status}`);
      await refreshAll();
    } catch (err) {
      setError(String(err));
    } finally {
      setTriggeringDream(false);
    }
  }, [refreshAll]);

  const patchSelected = useCallback(async (updates: Partial<MemoryItem>) => {
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/memory/items/${selected.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (res.status === 404) {
        fallbackStatus('Memory OS API is not available from the running backend. Restart the Desktop Agent backend before editing memories.');
        return;
      }
      if (!res.ok) throw new Error(`Save failed: ${res.status}`);
      const data = await res.json();
      setSelected(data.item);
      await refreshAll();
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }, [refreshAll, selected]);

  const deleteSelected = useCallback(async () => {
    if (!selected || !window.confirm('Delete this memory item from active recall?')) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/agents/personal/memory/items/${selected.id}`, { method: 'DELETE' });
      if (res.status === 404) {
        fallbackStatus('Memory OS API is not available from the running backend. Restart the Desktop Agent backend before deleting memories.');
        return;
      }
      if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
      setSelected(null);
      await refreshAll();
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }, [refreshAll, selected]);

  const moveTier = useCallback((direction: -1 | 1) => {
    if (!selected) return;
    const index = tierOrder.indexOf(selected.tier);
    const next = tierOrder[Math.min(tierOrder.length - 1, Math.max(0, index + direction))];
    if (next !== selected.tier) void patchSelected({ tier: next });
  }, [patchSelected, selected]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-border p-2">
        <div className="mb-2 rounded border border-border bg-surface-alt px-2 py-1.5 text-[11px] leading-relaxed text-fg-muted">
          记忆由 Agent 自动维护。你只需要查看、纠正或删除不准确内容，底层维护操作已收进高级区。
        </div>
        <div className="flex items-center gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-muted" />
            <input
              ref={searchInputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void runSearch();
              }}
              placeholder="查找 Agent 记住的内容"
              className="h-8 w-full rounded border border-border bg-surface-alt pl-7 pr-2 text-xs text-fg outline-none focus:border-accent"
            />
          </div>
          <button
            type="button"
            onClick={() => void runSearch()}
            className="flex h-8 items-center gap-1 rounded bg-accent px-2 text-xs text-fg-on-accent hover:brightness-110"
          >
            <Search className="h-3.5 w-3.5" />
            查找
          </button>
          <button
            type="button"
            onClick={() => setShowAdvanced((value) => !value)}
            className="flex h-8 items-center gap-1 rounded border border-border px-2 text-xs text-fg-muted hover:bg-surface-hover hover:text-fg"
            aria-expanded={showAdvanced}
          >
            {showAdvanced ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            高级维护
          </button>
        </div>
        {showAdvanced && (
          <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-border bg-surface-alt p-2">
            <select
              value={memoryType}
              onChange={(event) => setMemoryType(event.target.value as '' | MemoryType)}
              className="h-8 rounded border border-border bg-surface px-2 text-xs text-fg outline-none focus:border-accent"
              aria-label="Memory type"
            >
              {MEMORY_TYPES.map((type) => <option key={type.id || 'all'} value={type.id}>{type.label}</option>)}
            </select>
            <select
              value={tier}
              onChange={(event) => setTier(event.target.value as '' | MemoryTier)}
              className="h-8 rounded border border-border bg-surface px-2 text-xs text-fg outline-none focus:border-accent"
              aria-label="Memory tier"
            >
              {TIERS.map((item) => <option key={item.id || 'any'} value={item.id}>{item.label}</option>)}
            </select>
            <button
              type="button"
              onClick={rebuild}
              disabled={rebuilding}
              title="Rebuild index"
              className="flex h-8 items-center gap-1 rounded border border-border px-2 text-xs text-fg-muted hover:bg-surface-hover hover:text-fg disabled:opacity-50"
            >
              {rebuilding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              重建索引
            </button>
            <button
              type="button"
              onClick={triggerDream}
              disabled={triggeringDream}
              title="Trigger DREAM"
              className="flex h-8 items-center gap-1 rounded border border-border px-2 text-xs text-fg-muted hover:bg-surface-hover hover:text-fg disabled:opacity-50"
            >
              {triggeringDream ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
              手动整理记忆
            </button>
            <span className="text-[10px] text-fg-muted">仅用于调试或修复索引；日常由 Agent 自动处理。</span>
          </div>
        )}
        {error && <div className="mt-2 rounded border border-danger/40 bg-danger/10 px-2 py-1 text-[11px] text-danger">{error}</div>}
        {memoryOsUnavailable && !error && (
          <div className="mt-2 rounded border border-border bg-surface-alt px-2 py-1 text-[11px] text-fg-muted">
            {memoryOsUnavailable}
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-x-auto">
        <div className="grid h-full min-w-[760px] grid-cols-[170px_minmax(260px,1fr)_minmax(280px,0.95fr)]">
          <aside className="min-h-0 overflow-y-auto border-r border-border p-2">
            <div className="mb-3 flex items-center gap-1.5 text-xs font-medium text-fg">
              <Database className="h-3.5 w-3.5" />
              Agent 记忆
            </div>
            <div className="space-y-1 text-[11px] text-fg-muted">
              <div className="flex items-center justify-between rounded bg-surface-alt px-2 py-1">
                <span>Total</span>
                <span className="text-fg">{status?.total_items ?? 0}</span>
              </div>
              <div className="flex items-center justify-between rounded bg-surface-alt px-2 py-1">
                <span>Vector</span>
                <span className={status?.vector_available ? 'text-success' : 'text-fg-muted'}>
                  {status?.vector_available ? 'on' : 'off'}
                </span>
              </div>
              <div className="flex items-center justify-between rounded bg-surface-alt px-2 py-1">
                <span>Candidates</span>
                <span className="text-fg">{status?.pending_candidates ?? 0}</span>
              </div>
            </div>

            <div className="mt-4 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-fg-muted">
              <Layers className="h-3 w-3" />
              Types
            </div>
            <div className="mt-1 space-y-0.5">
              {MEMORY_TYPES.filter((type) => type.id).map((type) => (
                <button
                  key={type.id}
                  type="button"
                  onClick={() => setMemoryType(type.id as MemoryType)}
                  className={cn(
                    'flex w-full items-center justify-between rounded px-2 py-1 text-left text-[11px] hover:bg-surface-hover',
                    memoryType === type.id ? 'bg-surface-alt text-fg' : 'text-fg-muted'
                  )}
                >
                  <span>{type.label}</span>
                  <span>{status?.counts_by_type[type.id as MemoryType] || 0}</span>
                </button>
              ))}
            </div>

            <div className="mt-4 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-fg-muted">
              <Zap className="h-3 w-3" />
              Tiers
            </div>
            <div className="mt-1 space-y-0.5">
              {TIERS.filter((item) => item.id).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setTier(item.id as MemoryTier)}
                  className={cn(
                    'flex w-full items-center justify-between rounded px-2 py-1 text-left text-[11px] hover:bg-surface-hover',
                    tier === item.id ? 'bg-surface-alt text-fg' : 'text-fg-muted'
                  )}
                >
                  <span className={cn('font-medium', tierClass(item.id as MemoryTier))}>{item.label}</span>
                  <span>{status?.counts_by_tier[item.id as MemoryTier] || 0}</span>
                </button>
              ))}
            </div>

            <div className="mt-4 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-fg-muted">
              <Calendar className="h-3 w-3" />
              Diaries
            </div>
            <div className="mt-1 max-h-36 overflow-y-auto text-[11px] text-fg-muted">
              {diaries.length === 0 ? (
                <div className="px-2 py-1">No diaries</div>
              ) : diaries.slice(0, 12).map((diary) => (
                <div key={diary.date} className="flex justify-between gap-2 px-2 py-0.5">
                  <span className="truncate">{diary.date}</span>
                  <span>{(diary.size / 1024).toFixed(1)} KB</span>
                </div>
              ))}
            </div>
          </aside>

          <main className="min-h-0 overflow-y-auto border-r border-border">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-surface px-3 py-2">
              <span className="text-xs font-medium text-fg">{items.length} results</span>
              {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-fg-muted" />}
            </div>
            {items.length === 0 && !loading ? (
              <div className="p-6 text-center text-xs text-fg-muted">
                {memoryOsUnavailable
                  ? 'Memory OS is waiting for the updated backend. Legacy MEMORY.md and diaries remain available on the right.'
                  : '还没有可查看的长期记忆。Agent 会在对话和自动整理后逐步写入。'}
              </div>
            ) : (
              <div className="divide-y divide-border">
                {items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelected(item)}
                    className={cn(
                      'block w-full px-3 py-2 text-left transition-colors hover:bg-surface-hover',
                      selected?.id === item.id ? 'bg-surface-alt' : ''
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-xs font-medium text-fg">{item.summary || item.content}</span>
                      <span className="shrink-0 text-[10px] text-fg-muted">{item.score.toFixed(2)}</span>
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-[10px] text-fg-muted">
                      <span className={cn('font-medium uppercase', tierClass(item.tier))}>{item.tier}</span>
                      <span>{item.memory_type}</span>
                      <span className="truncate">{item.source_ref}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </main>

          <section className="min-h-0 overflow-y-auto p-3">
            {selected ? (
              <div className="space-y-3">
                <div>
                  <div className="mb-1 text-[11px] uppercase tracking-wider text-fg-muted">Details</div>
                  <div className="space-y-1 text-[11px] text-fg-muted">
                    <div className="flex justify-between gap-2"><span>Source</span><span className="truncate text-fg">{selected.source_ref}</span></div>
                    <div className="flex justify-between gap-2"><span>Updated</span><span className="text-fg">{formatTime(selected.updated_at)}</span></div>
                    <div className="flex justify-between gap-2"><span>Created by</span><span className="text-fg">{selected.created_by}</span></div>
                  </div>
                </div>

                <div>
                  <div className="mb-1 text-[11px] uppercase tracking-wider text-fg-muted">Content</div>
                  <div className="min-h-32 whitespace-pre-wrap rounded border border-border bg-surface-alt p-2 text-xs leading-relaxed text-fg">
                    {selected.content}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={deleteSelected}
                    disabled={saving}
                    title="Delete memory"
                    className="flex h-8 w-8 items-center justify-center rounded border border-danger/40 text-danger hover:bg-danger/10 disabled:opacity-40"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>

                {showAdvanced && (
                  <div className="space-y-2 rounded border border-border bg-surface-alt p-2">
                    <div className="text-[11px] font-medium text-fg">高级字段</div>
                    <div className="space-y-1 text-[11px] text-fg-muted">
                      <div className="flex justify-between gap-2"><span>Confidence</span><span className="text-fg">{selected.confidence.toFixed(2)}</span></div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <select
                        value={editType}
                        onChange={(event) => setEditType(event.target.value as MemoryType)}
                        className="h-8 rounded border border-border bg-surface px-2 text-xs text-fg outline-none focus:border-accent"
                        aria-label="Edit memory type"
                      >
                        {MEMORY_TYPES.filter((type) => type.id).map((type) => (
                          <option key={type.id} value={type.id}>{type.label}</option>
                        ))}
                      </select>
                      <select
                        value={editTier}
                        onChange={(event) => setEditTier(event.target.value as MemoryTier)}
                        className="h-8 rounded border border-border bg-surface px-2 text-xs text-fg outline-none focus:border-accent"
                        aria-label="Edit memory tier"
                      >
                        {TIERS.filter((item) => item.id).map((item) => (
                          <option key={item.id} value={item.id}>{item.label}</option>
                        ))}
                      </select>
                    </div>
                    <textarea
                      value={editContent}
                      onChange={(event) => setEditContent(event.target.value)}
                      className="min-h-32 w-full resize-y rounded border border-border bg-surface p-2 text-xs text-fg outline-none focus:border-accent"
                      aria-label="Memory content"
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void patchSelected({ content: editContent, memory_type: editType, tier: editTier })}
                        disabled={saving}
                        className="flex h-8 items-center gap-1 rounded bg-accent px-2 text-xs text-fg-on-accent hover:brightness-110 disabled:opacity-50"
                      >
                        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => moveTier(-1)}
                        disabled={saving || selected.tier === 'hot'}
                        title="Promote tier"
                        className="flex h-8 w-8 items-center justify-center rounded border border-border text-fg-muted hover:bg-surface-hover hover:text-fg disabled:opacity-40"
                      >
                        <ArrowUp className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => moveTier(1)}
                        disabled={saving || selected.tier === 'archived'}
                        title="Demote tier"
                        className="flex h-8 w-8 items-center justify-center rounded border border-border text-fg-muted hover:bg-surface-hover hover:text-fg disabled:opacity-40"
                      >
                        <ArrowDown className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <div className="mb-1 text-xs font-medium text-fg">MEMORY.md</div>
                  <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap rounded border border-border bg-surface-alt p-2 text-[11px] text-fg-muted">
                    {memoryContent || '(Empty - DREAM will populate this)'}
                  </pre>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
};
