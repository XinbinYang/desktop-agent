import React, { useState, useEffect, useCallback } from 'react';
import { Plug, Plus, Trash2, Loader2, RefreshCw, Link2, Unlink } from 'lucide-react';
import { API_BASE } from '../config';

interface McpServer {
  id: string;
  config: {
    transport: string;
    command?: string;
    args?: string[];
    url?: string;
  };
  connected: boolean;
  tools: { name: string; description: string }[];
  error?: string;
}

export function McpPanel() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [newServer, setNewServer] = useState({
    id: '',
    transport: 'stdio' as 'stdio' | 'sse',
    command: '',
    args: '',
    url: '',
  });

  const loadServers = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/mcp/servers`);
      const data = await res.json();
      setServers(data.servers || []);
    } catch (err) {
      console.error('Failed to load MCP servers:', err);
    }
  }, []);

  useEffect(() => {
    loadServers();
    const interval = setInterval(loadServers, 30000);
    return () => clearInterval(interval);
  }, [loadServers]);

  const handleConnect = async (id: string) => {
    setConnectingId(id);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/mcp/servers/${id}/connect`, { method: 'POST' });
      const data = await res.json();
      if (!data.connected) {
        setError(`连接失败: ${id}`);
      }
      await loadServers();
    } catch (err) {
      setError(`连接失败: ${err}`);
    } finally {
      setConnectingId(null);
    }
  };

  const handleDisconnect = async (id: string) => {
    setConnectingId(id);
    setError(null);
    try {
      await fetch(`${API_BASE}/api/mcp/servers/${id}/disconnect`, { method: 'POST' });
      await loadServers();
    } catch (err) {
      setError(`断开失败: ${err}`);
    } finally {
      setConnectingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(`确定要删除 MCP Server "${id}" 吗？`)) return;
    setLoading(true);
    setError(null);
    try {
      await fetch(`${API_BASE}/api/mcp/servers/${id}`, { method: 'DELETE' });
      await loadServers();
    } catch (err) {
      setError(`删除失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async () => {
    if (!newServer.id.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const body: any = {
        id: newServer.id.trim(),
        transport: newServer.transport,
      };
      if (newServer.transport === 'stdio') {
        body.command = newServer.command || undefined;
        body.args = newServer.args ? newServer.args.split(' ').filter(Boolean) : [];
      } else {
        body.url = newServer.url || undefined;
      }
      const res = await fetch(`${API_BASE}/api/mcp/servers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        setShowAdd(false);
        setNewServer({ id: '', transport: 'stdio', command: '', args: '', url: '' });
        await loadServers();
      } else {
        setError('添加失败');
      }
    } catch (err) {
      setError(`添加失败: ${err}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full flex flex-col text-sm">
      <div className="px-3 py-2 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Plug size={14} className="text-success" />
          <span className="font-semibold text-fg">MCP Servers</span>
          {loading && <Loader2 size={14} className="animate-spin text-fg-secondary" />}
        </div>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="px-1.5 py-0.5 bg-accent/85 hover:bg-accent rounded text-fg-on-accent"
        >
          <Plus size={12} />
        </button>
      </div>

      {showAdd && (
        <div className="px-3 py-2 border-b border-border space-y-1">
          <input
            type="text"
            value={newServer.id}
            onChange={(e) => setNewServer({ ...newServer, id: e.target.value })}
            placeholder="Server ID"
            className="w-full bg-surface border border-border-subtle rounded px-2 py-1 text-xs text-fg placeholder-fg-muted focus:outline-none focus:border-accent"
          />
          <select
            value={newServer.transport}
            onChange={(e) => setNewServer({ ...newServer, transport: e.target.value as 'stdio' | 'sse' })}
            className="w-full bg-surface border border-border-subtle rounded px-2 py-1 text-xs text-fg"
          >
            <option value="stdio">stdio</option>
            <option value="sse">sse</option>
          </select>
          {newServer.transport === 'stdio' ? (
            <>
              <input
                type="text"
                value={newServer.command}
                onChange={(e) => setNewServer({ ...newServer, command: e.target.value })}
                placeholder="Command (e.g. npx)"
                className="w-full bg-surface border border-border-subtle rounded px-2 py-1 text-xs text-fg placeholder-fg-muted focus:outline-none focus:border-accent"
              />
              <input
                type="text"
                value={newServer.args}
                onChange={(e) => setNewServer({ ...newServer, args: e.target.value })}
                placeholder="Args (space separated)"
                className="w-full bg-surface border border-border-subtle rounded px-2 py-1 text-xs text-fg placeholder-fg-muted focus:outline-none focus:border-accent"
              />
            </>
          ) : (
            <input
              type="text"
              value={newServer.url}
              onChange={(e) => setNewServer({ ...newServer, url: e.target.value })}
              placeholder="SSE URL"
              className="w-full bg-surface border border-border-subtle rounded px-2 py-1 text-xs text-fg placeholder-fg-muted focus:outline-none focus:border-accent"
            />
          )}
          <div className="flex gap-1">
            <button onClick={handleAdd} className="flex-1 py-1 bg-accent/85 hover:bg-accent rounded text-xs text-fg-on-accent">添加</button>
            <button onClick={() => setShowAdd(false)} className="flex-1 py-1 bg-surface-alt hover:bg-surface-hover rounded text-xs text-fg-secondary">取消</button>
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="px-3 py-1.5 bg-danger/10 border-b border-danger/30 flex items-center justify-between">
          <span className="text-xs text-danger">{error}</span>
          <button onClick={() => setError(null)} className="text-danger hover:text-danger/80 text-xs">✕</button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-2">
        {servers.length === 0 ? (
          <div className="text-xs text-fg-muted text-center mt-4">暂无 MCP Server 配置</div>
        ) : (
          <div className="space-y-2">
            {servers.map((s) => (
              <div key={s.id} className="bg-surface rounded p-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1 min-w-0">
                    {connectingId === s.id ? (
                      <Loader2 size={10} className="animate-spin text-warning shrink-0" />
                    ) : (
                      <div className={`w-2 h-2 rounded-full shrink-0 ${s.connected ? 'bg-success' : 'bg-surface-hover'}`} />
                    )}
                    <span className="text-xs text-fg font-medium truncate">{s.id}</span>
                    <span className="text-[10px] text-fg-muted shrink-0">({s.config.transport})</span>
                    {s.tools.length > 0 && (
                      <span className="text-[10px] bg-surface-alt text-fg-secondary rounded-full px-1.5 shrink-0">{s.tools.length} tools</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0 ml-1">
                    {s.connected ? (
                      <button onClick={() => handleDisconnect(s.id)} disabled={connectingId === s.id} className="px-1 py-0.5 text-warning hover:text-warning/80 disabled:opacity-50" title="断开">
                        <Unlink size={10} />
                      </button>
                    ) : (
                      <button onClick={() => handleConnect(s.id)} disabled={connectingId === s.id} className="px-1 py-0.5 text-success hover:text-success/80 disabled:opacity-50" title="连接">
                        <Link2 size={10} />
                      </button>
                    )}
                    <button onClick={() => handleDelete(s.id)} disabled={connectingId === s.id} className="px-1 py-0.5 text-danger hover:text-danger/80 disabled:opacity-50" title="删除">
                      <Trash2 size={10} />
                    </button>
                  </div>
                </div>
                {s.error && <div className="text-[10px] text-danger mt-1">{s.error}</div>}
                {s.tools.length > 0 && (
                  <div className="mt-1 space-y-0.5">
                    {s.tools.map((t) => (
                      <div key={t.name} className="text-[10px] text-fg-secondary" title={t.description || t.name}>
                        {t.name}{t.description ? ` — ${t.description.slice(0, 80)}${t.description.length > 80 ? '...' : ''}` : ''}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
