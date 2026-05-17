import React, { useState, useEffect, useCallback, useRef } from 'react';
import { BookOpen, Plus, Trash2, Search, Loader2, FolderOpen, X, RefreshCw } from 'lucide-react';
import { KnowledgeDoc, KnowledgeSearchResult } from '../types';
import { API_BASE } from '../config';
import { loadKnowledgePaths, saveKnowledgePath, deleteKnowledgePath } from '../lib/db';

interface SavedPath {
  path: string;
  recursive: boolean;
  addedAt: number;
}

export function KnowledgePanel() {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [searchResults, setSearchResults] = useState<KnowledgeSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [inputPath, setInputPath] = useState('');
  const [recursive, setRecursive] = useState(true);
  const [savedPaths, setSavedPaths] = useState<SavedPath[]>([]);
  const [reindexingPath, setReindexingPath] = useState<string | null>(null);
  const [stats, setStats] = useState<{ total_chunks: number; source_count: number; db_size_mb: number } | null>(null);
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
        setError(`重新索引失败: ${data.error}`);
      } else {
        await loadDocs();
      }
    } catch (err) {
      setError(`重新索引失败: ${err}`);
    } finally {
      setReindexingPath(null);
    }
  };

  const handleRemovePath = async (path: string) => {
    await deleteKnowledgePath(path);
    await loadSavedPaths();
  };

  const handleAdd = async () => {
    if (!inputPath.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/knowledge/index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: inputPath.trim(), recursive }),
      });
      const data = await res.json();
      if (data.error) {
        setError(`索引失败: ${data.error}`);
      } else {
        await saveKnowledgePath(inputPath.trim(), recursive);
        setInputPath('');
        await loadDocs();
      }
    } catch (err) {
      setError(`索引失败: ${err}`);
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
    if (!confirm(`确定要删除 "${path}" 的索引吗？`)) return;
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/knowledge/docs?path=${encodeURIComponent(path)}`, {
        method: 'DELETE',
      });
      await deleteKnowledgePath(path);
      await loadDocs();
    } catch (err) {
      console.error('Failed to delete doc:', err);
    } finally {
      setLoading(false);
    }
  };

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) return;
    setSearching(true);
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
    }
  };

  return (
    <div className="h-full flex flex-col text-sm">
      {/* Error banner */}
      {error && (
        <div className="px-3 py-1.5 bg-danger/10 border-b border-danger/30 flex items-center justify-between">
          <span className="text-xs text-danger">{error}</span>
          <button type="button" onClick={() => setError(null)} className="text-danger hover:text-danger/80 text-xs"><X size={12} /></button>
        </div>
      )}

      {/* Header */}
      <div className="px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2 mb-1">
          <BookOpen size={14} className="text-accent" />
          <span className="font-semibold text-fg">知识库</span>
          {loading && <Loader2 size={14} className="animate-spin text-fg-secondary" />}
        </div>
        {stats && stats.total_chunks > 0 && (
          <div className="text-[10px] text-fg-muted mb-1">
            {stats.source_count} 文件 · {stats.total_chunks} 块 · {stats.db_size_mb} MB
          </div>
        )}
        <div className="flex gap-1">
          <input
            type="text"
            value={inputPath}
            onChange={(e) => setInputPath(e.target.value)}
            placeholder="输入文件或文件夹路径..."
            className="flex-1 bg-surface border border-border-subtle rounded px-2 py-1 text-xs text-fg placeholder-fg-muted focus:outline-none focus:border-accent"
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          />
          <button
            onClick={handlePickFolder}
            title="选择文件夹"
            className="px-2 py-1 bg-surface-alt hover:bg-surface-hover rounded text-fg-secondary"
          >
            <FolderOpen size={14} />
          </button>
          <button
            onClick={handleAdd}
            disabled={loading || !inputPath.trim()}
            className="px-2 py-1 bg-accent/85 hover:bg-accent disabled:opacity-50 rounded text-fg-on-accent"
          >
            <Plus size={14} />
          </button>
        </div>
        <label className="flex items-center gap-1 mt-1 text-xs text-fg-secondary">
          <input
            type="checkbox"
            checked={recursive}
            onChange={(e) => setRecursive(e.target.checked)}
            className="rounded"
          />
          递归索引子文件夹
        </label>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-border">
        <div className="flex gap-1">
          <input
            type="text"
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="搜索知识库..."
            className="flex-1 bg-surface border border-border-subtle rounded px-2 py-1 text-xs text-fg placeholder-fg-muted focus:outline-none focus:border-accent"
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <button
            onClick={handleSearch}
            disabled={searching || !query.trim()}
            className="px-2 py-1 bg-surface-alt hover:bg-surface-hover disabled:opacity-50 rounded text-fg-secondary"
          >
            {searching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          </button>
        </div>
      </div>

      {/* Search results */}
      {searchResults.length > 0 && (
        <div className="px-3 py-2 border-b border-border max-h-48 overflow-y-auto">
          <div className="text-xs font-semibold text-fg-secondary mb-1">搜索结果</div>
          {searchResults.map((r) => (
            <div key={r.chunk_id} className="mb-2 p-2 bg-surface rounded">
              <div className="text-xs text-accent truncate">{r.source_path}</div>
              <div className="text-xs text-fg-muted">相关度: {r.score}</div>
              <div className="text-xs text-fg-secondary mt-1 line-clamp-3 whitespace-pre-wrap">{r.content}</div>
            </div>
          ))}
          <button
            onClick={() => setSearchResults([])}
            className="text-xs text-fg-muted hover:text-fg-secondary"
          >
            清除结果
          </button>
        </div>
      )}

      {/* Saved paths — quick reindex */}
      {savedPaths.length > 0 && (
        <div className="px-3 py-2 border-b border-border">
          <div className="text-xs font-semibold text-fg-secondary mb-1">已保存路径</div>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {savedPaths.map((sp) => (
              <div key={sp.path} className="flex items-center justify-between bg-surface rounded px-2 py-1">
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-fg-secondary truncate" title={sp.path}>{sp.path}</div>
                  <div className="text-[10px] text-fg-muted">
                    {sp.recursive ? '递归' : '非递归'} · {new Date(sp.addedAt).toLocaleDateString()}
                  </div>
                </div>
                <div className="flex items-center gap-1 ml-2">
                  <button
                    type="button"
                    onClick={() => handleReindex(sp.path, sp.recursive)}
                    disabled={reindexingPath === sp.path}
                    className="px-1 py-0.5 text-accent hover:text-accent/80 disabled:opacity-50"
                    title="重新索引"
                  >
                    {reindexingPath === sp.path ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRemovePath(sp.path)}
                    className="px-1 py-0.5 text-danger hover:text-danger/80"
                    title="移除路径"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Doc list */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {docs.length === 0 && savedPaths.length === 0 ? (
          <div className="text-xs text-fg-muted text-center mt-4">知识库为空，添加文件或文件夹开始索引</div>
        ) : docs.length === 0 ? (
          <div className="text-xs text-fg-muted text-center mt-4">点击上方路径旁的刷新按钮重新索引</div>
        ) : (
          <div className="space-y-1">
            {docs.map((doc) => (
              <div
                key={doc.source_path}
                className="flex items-center justify-between p-2 bg-surface rounded hover:bg-surface-hover group"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-fg-secondary truncate">{doc.source_path}</div>
                  <div className="text-xs text-fg-muted">{doc.chunk_count} chunks</div>
                </div>
                <button
                  onClick={() => handleDelete(doc.source_path)}
                  className="opacity-0 group-hover:opacity-100 px-1 py-1 text-danger hover:text-danger/80 transition-opacity"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
