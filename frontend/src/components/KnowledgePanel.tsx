import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  BookOpen,
  Plus,
  Trash2,
  Search,
  Loader2,
  FolderOpen,
  X,
  RefreshCw,
  Database,
  FileText,
  Layers,
} from 'lucide-react';
import { KnowledgeDoc, KnowledgeSearchResult } from '../types';
import { API_BASE } from '../config';
import { loadKnowledgePaths, saveKnowledgePath, deleteKnowledgePath } from '../lib/db';

interface SavedPath {
  path: string;
  recursive: boolean;
  addedAt: number;
}

interface KnowledgeStats {
  total_chunks: number;
  source_count: number;
  db_size_mb: number;
  embedding_model?: string;
  embedding_dim?: number;
}

function formatIndexedAt(value?: number): string {
  if (!value) return 'Never';
  return new Date(value * 1000).toLocaleString();
}

function formatSavedAt(value?: number): string {
  if (!value) return 'Unknown';
  return new Date(value).toLocaleDateString();
}

function basename(path: string): string {
  return path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || path;
}

export function KnowledgePanel() {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [searchResults, setSearchResults] = useState<KnowledgeSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [inputPath, setInputPath] = useState('');
  const [recursive, setRecursive] = useState(true);
  const [savedPaths, setSavedPaths] = useState<SavedPath[]>([]);
  const [reindexingPath, setReindexingPath] = useState<string | null>(null);
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadDocs = useCallback(async () => {
    try {
      const [docsRes, statsRes] = await Promise.all([
        fetch(`${API_BASE}/api/knowledge/docs`),
        fetch(`${API_BASE}/api/knowledge/stats`),
      ]);
      const docsData = await docsRes.json();
      const statsData = await statsRes.json();
      setDocs(docsData.docs || []);
      if (statsData.total_chunks !== undefined) setStats(statsData);
    } catch (err) {
      console.error('Failed to load knowledge data:', err);
      setError(`Failed to load knowledge data: ${err}`);
    }
  }, []);

  const loadSavedPaths = useCallback(async () => {
    try {
      const paths = await loadKnowledgePaths();
      setSavedPaths(paths.sort((a, b) => b.addedAt - a.addedAt));
    } catch (err) {
      console.error('Failed to load saved paths:', err);
    }
  }, []);

  useEffect(() => {
    loadDocs();
    loadSavedPaths();
  }, [loadDocs, loadSavedPaths]);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadDocs(), loadSavedPaths()]);
  }, [loadDocs, loadSavedPaths]);

  const handleReindex = async (path: string, rec: boolean) => {
    setReindexingPath(path);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, recursive: rec }),
      });
      const data = await res.json();
      if (data.error) {
        setError(`Reindex failed: ${data.error}`);
      } else {
        await loadDocs();
      }
    } catch (err) {
      setError(`Reindex failed: ${err}`);
    } finally {
      setReindexingPath(null);
    }
  };

  const handleRemovePath = async (path: string) => {
    await deleteKnowledgePath(path);
    await loadSavedPaths();
  };

  const handleAdd = async () => {
    const path = inputPath.trim();
    if (!path) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, recursive }),
      });
      const data = await res.json();
      if (data.error) {
        setError(`Index failed: ${data.error}`);
      } else {
        await saveKnowledgePath(path, recursive);
        setInputPath('');
        await refreshAll();
      }
    } catch (err) {
      setError(`Index failed: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const handlePickFolder = async () => {
    if (window.electronAPI?.selectFolder) {
      const path = await window.electronAPI.selectFolder();
      if (path) setInputPath(path);
    }
  };

  const handleDelete = async (path: string) => {
    if (!confirm(`Remove "${path}" from the knowledge index?`)) return;
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/knowledge/docs?path=${encodeURIComponent(path)}`, {
        method: 'DELETE',
      });
      await deleteKnowledgePath(path);
      await refreshAll();
    } catch (err) {
      setError(`Delete failed: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const handleClearAll = async () => {
    if (!confirm('Clear the entire knowledge index? Source files will not be deleted.')) return;
    setLoading(true);
    setError(null);
    try {
      await fetch(`${API_BASE}/api/knowledge`, { method: 'DELETE' });
      await Promise.all(savedPaths.map((sp) => deleteKnowledgePath(sp.path)));
      setSearchResults([]);
      setHasSearched(false);
      await refreshAll();
    } catch (err) {
      setError(`Clear failed: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setSearchResults([]);
      setHasSearched(false);
      return;
    }
    setSearching(true);
    setHasSearched(true);
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q.trim(), top_k: 5 }),
      });
      const data = await res.json();
      setSearchResults(data.results || []);
    } catch (err) {
      console.error('Search failed:', err);
      setError(`Search failed: ${err}`);
    } finally {
      setSearching(false);
    }
  }, []);

  const handleSearch = () => {
    doSearch(query);
  };

  const handleQueryChange = (value: string) => {
    setQuery(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (value.trim().length >= 2) {
      searchTimerRef.current = setTimeout(() => doSearch(value), 300);
    } else {
      setSearchResults([]);
      setHasSearched(false);
    }
  };

  const totalSources = stats?.source_count ?? docs.length;
  const totalChunks = stats?.total_chunks ?? docs.reduce((sum, doc) => sum + doc.chunk_count, 0);

  return (
    <div className="h-full flex flex-col text-sm text-fg">
      {error && (
        <div className="px-4 py-2 bg-danger/10 border-b border-danger/30 flex items-center justify-between gap-3">
          <span className="text-xs text-danger">{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-danger hover:text-danger/80"
            aria-label="Dismiss knowledge error"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <div className="px-4 py-3 border-b border-border space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <BookOpen size={16} className="text-accent" />
              <h3 className="font-semibold text-fg">Knowledge Base</h3>
              {loading && <Loader2 size={14} className="animate-spin text-fg-secondary" />}
            </div>
            <div className="mt-1 text-xs text-fg-muted">
              Auto context is used only when indexed content matches the current chat turn.
            </div>
          </div>
          <button
            type="button"
            onClick={refreshAll}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-alt px-2 py-1 text-xs text-fg-secondary hover:bg-surface-hover"
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <div className="rounded-md border border-border-subtle bg-surface px-3 py-2">
            <div className="flex items-center gap-1.5 text-[11px] text-fg-muted">
              <FileText size={12} />
              Sources
            </div>
            <div className="mt-1 text-base font-semibold text-fg">{totalSources}</div>
          </div>
          <div className="rounded-md border border-border-subtle bg-surface px-3 py-2">
            <div className="flex items-center gap-1.5 text-[11px] text-fg-muted">
              <Layers size={12} />
              Chunks
            </div>
            <div className="mt-1 text-base font-semibold text-fg">{totalChunks}</div>
          </div>
          <div className="rounded-md border border-border-subtle bg-surface px-3 py-2">
            <div className="flex items-center gap-1.5 text-[11px] text-fg-muted">
              <Database size={12} />
              Database
            </div>
            <div className="mt-1 text-base font-semibold text-fg">{stats?.db_size_mb ?? 0} MB</div>
          </div>
        </div>

        {stats?.embedding_model && (
          <div className="text-[11px] text-fg-muted truncate">
            Embeddings: {stats.embedding_model}{stats.embedding_dim ? ` (${stats.embedding_dim}d)` : ''}
          </div>
        )}
      </div>

      <div className="px-4 py-3 border-b border-border space-y-2">
        <div className="flex gap-2">
          <input
            type="text"
            value={inputPath}
            onChange={(e) => setInputPath(e.target.value)}
            placeholder="File or folder path"
            className="flex-1 bg-surface border border-border-subtle rounded-md px-2 py-1.5 text-xs text-fg placeholder-fg-muted focus:outline-none focus:border-accent"
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          />
          <button
            type="button"
            onClick={handlePickFolder}
            title="Choose folder"
            aria-label="Choose folder"
            className="px-2 py-1.5 bg-surface-alt hover:bg-surface-hover rounded-md text-fg-secondary"
          >
            <FolderOpen size={15} />
          </button>
          <button
            type="button"
            onClick={handleAdd}
            disabled={loading || !inputPath.trim()}
            aria-label="Add to knowledge base"
            className="px-2 py-1.5 bg-accent/85 hover:bg-accent disabled:opacity-50 rounded-md text-fg-on-accent"
          >
            <Plus size={15} />
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-fg-secondary">
          <input
            type="checkbox"
            checked={recursive}
            onChange={(e) => setRecursive(e.target.checked)}
            className="rounded"
          />
          Include subfolders
        </label>
      </div>

      <div className="px-4 py-3 border-b border-border">
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="Search indexed content"
            className="flex-1 bg-surface border border-border-subtle rounded-md px-2 py-1.5 text-xs text-fg placeholder-fg-muted focus:outline-none focus:border-accent"
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <button
            type="button"
            onClick={handleSearch}
            disabled={searching || !query.trim()}
            aria-label="Search knowledge base"
            className="px-2 py-1.5 bg-surface-alt hover:bg-surface-hover disabled:opacity-50 rounded-md text-fg-secondary"
          >
            {searching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {searchResults.length > 0 && (
          <section className="px-4 py-3 border-b border-border">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-semibold text-fg-secondary">Search Results</div>
              <button
                type="button"
                onClick={() => {
                  setSearchResults([]);
                  setHasSearched(false);
                }}
                className="text-xs text-fg-muted hover:text-fg-secondary"
              >
                Clear
              </button>
            </div>
            <div className="space-y-2">
              {searchResults.map((r) => (
                <div key={r.chunk_id} className="rounded-md border border-border-subtle bg-surface px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs text-accent truncate" title={r.source_path}>{r.source_path}</div>
                    <div className="text-[10px] text-fg-muted shrink-0">{Math.round(r.score * 100)}%</div>
                  </div>
                  <div className="mt-1 text-xs text-fg-secondary line-clamp-3 whitespace-pre-wrap">{r.content}</div>
                </div>
              ))}
            </div>
          </section>
        )}

        {hasSearched && !searching && searchResults.length === 0 && (
          <div className="px-4 py-3 border-b border-border text-xs text-fg-muted">
            No matching indexed content.
          </div>
        )}

        {savedPaths.length > 0 && (
          <section className="px-4 py-3 border-b border-border">
            <div className="text-xs font-semibold text-fg-secondary mb-2">Saved Sources</div>
            <div className="space-y-2">
              {savedPaths.map((sp) => (
                <div key={sp.path} className="flex items-center justify-between gap-2 rounded-md border border-border-subtle bg-surface px-3 py-2">
                  <div className="min-w-0">
                    <div className="text-xs text-fg-secondary truncate" title={sp.path}>{sp.path}</div>
                    <div className="mt-0.5 text-[10px] text-fg-muted">
                      {sp.recursive ? 'Subfolders included' : 'Top level only'} - saved {formatSavedAt(sp.addedAt)}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={() => handleReindex(sp.path, sp.recursive)}
                      disabled={reindexingPath === sp.path}
                      className="p-1 text-accent hover:text-accent/80 disabled:opacity-50"
                      title="Reindex"
                      aria-label={`Reindex ${sp.path}`}
                    >
                      {reindexingPath === sp.path ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRemovePath(sp.path)}
                      className="p-1 text-danger hover:text-danger/80"
                      title="Remove saved source"
                      aria-label={`Remove saved source ${sp.path}`}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        <section className="px-4 py-3">
          <div className="flex items-center justify-between gap-2 mb-2">
            <div className="text-xs font-semibold text-fg-secondary">Indexed Documents</div>
            {(docs.length > 0 || savedPaths.length > 0) && (
              <button
                type="button"
                onClick={handleClearAll}
                className="text-xs text-danger hover:text-danger/80"
              >
                Clear all
              </button>
            )}
          </div>

          {docs.length === 0 && savedPaths.length === 0 ? (
            <div className="text-xs text-fg-muted text-center py-8">
              The knowledge base is empty.
            </div>
          ) : docs.length === 0 ? (
            <div className="text-xs text-fg-muted text-center py-8">
              Reindex a saved source to rebuild the document list.
            </div>
          ) : (
            <div className="space-y-2">
              {docs.map((doc) => (
                <div
                  key={doc.source_path}
                  className="flex items-center justify-between gap-3 rounded-md border border-border-subtle bg-surface px-3 py-2 hover:bg-surface-hover group"
                >
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-fg-secondary truncate" title={doc.source_path}>
                      {basename(doc.source_path)}
                    </div>
                    <div className="text-[10px] text-fg-muted truncate" title={doc.source_path}>{doc.source_path}</div>
                    <div className="mt-0.5 text-[10px] text-fg-muted">
                      {doc.chunk_count} chunks - indexed {formatIndexedAt(doc.last_indexed)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDelete(doc.source_path)}
                    className="p-1 text-danger hover:text-danger/80 opacity-0 group-hover:opacity-100 transition-opacity"
                    aria-label={`Delete ${doc.source_path}`}
                    title="Delete index"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
