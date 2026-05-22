import React, { useState, useEffect, useCallback } from 'react';
import { Plug, Play, Square, RotateCw, Loader2, Eye, EyeOff, Save, Trash2, Send } from 'lucide-react';
import { API_BASE } from '../config';
import type { ConnectorInfo } from '../types';

type EditState = {
  connectorName: string;
  fields: Record<string, string | boolean>;
  showValue: Record<string, boolean>;
};

function fmtUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function errorDetailMessage(detail: any, fallback: string): string {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (typeof detail.message === 'string') return detail.message;
  try {
    return JSON.stringify(detail);
  } catch {
    return fallback;
  }
}

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

export function ConnectionsPanel() {
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [operatingId, setOperatingId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testStatus, setTestStatus] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<EditState | null>(null);

  const loadConnectors = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/connectors`);
      const data = await res.json();
      setConnectors(data.connectors || []);
    } catch (err) {
      console.error('Failed to load connectors:', err);
    }
  }, []);

  useEffect(() => {
    loadConnectors();
    const interval = setInterval(loadConnectors, 10000);
    return () => clearInterval(interval);
  }, [loadConnectors]);

  const handleStart = async (name: string) => {
    setOperatingId(name);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/connectors/${name}/start`, { method: 'POST' });
      if (!res.ok) {
        const detail = await res.json();
        setError(errorDetailMessage(detail.detail, `启动失败: ${name}`));
      }
      await loadConnectors();
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        setError(`保存超时：后端 ${API_BASE} 当前无响应，请稍后重试或重启后端。`);
        return false;
      }
      setError(`启动失败: ${err.message || err}`);
    } finally {
      setOperatingId(null);
    }
  };

  const handleStop = async (name: string) => {
    setOperatingId(name);
    setError(null);
    try {
      await fetch(`${API_BASE}/api/connectors/${name}/stop`, { method: 'POST' });
      await loadConnectors();
    } catch (err: any) {
      setError(`停止失败: ${err.message || err}`);
    } finally {
      setOperatingId(null);
    }
  };

  const handleRestart = async (name: string) => {
    setOperatingId(name);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/connectors/${name}/restart`, { method: 'POST' });
      if (!res.ok) {
        const detail = await res.json();
        setError(errorDetailMessage(detail.detail, `重启失败: ${name}`));
      }
      await loadConnectors();
    } catch (err: any) {
      setError(`重启失败: ${err.message || err}`);
    } finally {
      setOperatingId(null);
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`确定要删除 "${name}" 连接配置吗？`)) return;
    setOperatingId(name);
    setError(null);
    try {
      await fetch(`${API_BASE}/api/connectors/${name}`, { method: 'DELETE' });
      await loadConnectors();
    } catch (err: any) {
      setError(`删除失败: ${err.message || err}`);
    } finally {
      setOperatingId(null);
    }
  };

  const startEdit = (c: ConnectorInfo) => {
    const schema = c.config_schema;
    const fields: Record<string, string | boolean> = {};
    const showValue: Record<string, boolean> = {};
    const props = schema?.properties || {};

    for (const key of Object.keys(props)) {
      const stored = c.config?.[key];
      if (props[key]?.sensitive && stored && typeof stored === 'object') {
        fields[key] = '';
      } else {
        fields[key] = stored ?? props[key]?.default ?? (props[key]?.type === 'boolean' ? false : '');
      }
      showValue[key] = !props[key]?.sensitive;
    }

    setEditing({ connectorName: c.name, fields, showValue });
  };

  const cancelEdit = () => {
    setEditing(null);
  };

  const updateField = (key: string, value: string | boolean) => {
    if (!editing) return;
    setEditing({ ...editing, fields: { ...editing.fields, [key]: value } });
  };

  const toggleShow = (key: string) => {
    if (!editing) return;
    setEditing({ ...editing, showValue: { ...editing.showValue, [key]: !editing.showValue[key] } });
  };

  const saveConnectorConfig = async (edit: EditState, closeOnSuccess: boolean) => {
    setOperatingId(edit.connectorName);
    setError(null);
    try {
      const res = await fetchWithTimeout(`${API_BASE}/api/connectors/${edit.connectorName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: edit.fields }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(errorDetailMessage(data.detail, `Save failed: ${edit.connectorName}`));
      }
      if (closeOnSuccess) {
        setEditing(null);
      }
      await loadConnectors();
      return true;
    } catch (err: any) {
      setError(`保存失败: ${err.message || err}`);
      return false;
    } finally {
      setOperatingId(null);
    }
  };

  const handleSave = async () => {
    if (!editing) return;
    await saveConnectorConfig(editing, true);
  };

  const handleTestMessage = async (name: string) => {
    if (editing?.connectorName === name) {
      const saved = await saveConnectorConfig(editing, false);
      if (!saved) return;
    }
    setTestingId(name);
    setError(null);
    setTestStatus((prev) => ({ ...prev, [name]: '' }));
    try {
      const res = await fetchWithTimeout(`${API_BASE}/api/connectors/${name}/test-message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'Desktop Agent connector test message.' }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(errorDetailMessage(data.detail, 'Test message failed'));
      }
      setTestStatus((prev) => ({ ...prev, [name]: 'Test message sent' }));
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        setError(`Test message failed: 后端 ${API_BASE} 当前无响应，请稍后重试或重启后端。`);
        return;
      }
      setError(`Test message failed: ${err.message || err}`);
    } finally {
      setTestingId(null);
    }
  };

  const statusColor = (status: string): string => {
    switch (status) {
      case 'running': return 'bg-success';
      case 'error': return 'bg-danger';
      default: return 'bg-border';
    }
  };

  const statusLabel = (status: string): string => {
    switch (status) {
      case 'running': return '运行中';
      case 'error': return '错误';
      default: return '已停止';
    }
  };

  const hasConfig = (c: ConnectorInfo) => {
    const schema = c.config_schema;
    return schema?.properties && Object.keys(schema.properties).length > 0;
  };

  const hasNotificationConfig = (c: ConnectorInfo) => {
    const props = c.config_schema?.properties || {};
    return Object.keys(props).some((key) => key.startsWith('notification') || key === 'notifications_enabled');
  };

  return (
    <div className="h-full flex flex-col text-sm">
      <div className="px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2">
          <Plug size={14} className="text-accent" />
          <span className="font-semibold text-fg">平台连接</span>
        </div>
        <p className="text-[10px] text-fg-muted mt-0.5">
          管理外部社交平台连接，远程与 Agent 对话
        </p>
      </div>

      {error && (
        <div className="px-3 py-1.5 bg-danger/10 border-b border-danger/35 flex items-center justify-between">
          <span className="text-xs text-danger">{error}</span>
          <button onClick={() => setError(null)} className="text-danger hover:text-danger/80 text-xs">&times;</button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-2">
        {connectors.length === 0 ? (
          <div className="text-xs text-fg-muted text-center mt-4">暂无连接的平台</div>
        ) : (
          <div className="space-y-2">
            {connectors.map((c) => {
              const uptime = (c as any).uptime_seconds || 0;
              return (
                <div key={c.name} className="bg-surface-alt/35 border border-border-subtle rounded p-3 transition-colors hover:border-border">
                  {/* Header */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      {operatingId === c.name ? (
                        <Loader2 size={12} className="animate-spin text-warning shrink-0" />
                      ) : (
                        <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${statusColor(c.status)} ${
                          c.status === 'running' ? 'animate-pulse' : ''
                        }`} />
                      )}
                      <span className="text-xs text-fg font-medium">{c.display_name}</span>
                      <span className="text-[10px] text-fg-muted">({statusLabel(c.status)})</span>
                      {c.status === 'running' && uptime > 0 && (
                        <span className="text-[10px] text-fg-muted ml-1">{fmtUptime(uptime)}</span>
                      )}
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      {c.status === 'running' ? (
                        <>
                          <button
                            onClick={() => handleRestart(c.name)}
                            disabled={operatingId === c.name}
                            className="p-1 text-fg-muted hover:text-fg disabled:opacity-50"
                            title="重启"
                          >
                            <RotateCw size={10} />
                          </button>
                          <button
                            onClick={() => handleStop(c.name)}
                            disabled={operatingId === c.name}
                            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-warning/10 text-warning border border-warning/25 hover:bg-warning/15 disabled:opacity-50"
                          >
                            <Square size={10} />
                            停止
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => handleStart(c.name)}
                          disabled={operatingId === c.name}
                          className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] bg-success/10 text-success border border-success/25 hover:bg-success/15 disabled:opacity-50"
                        >
                          <Play size={10} />
                          启动
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(c.name)}
                        disabled={operatingId === c.name || c.status === 'running'}
                        className="p-1 text-fg-muted hover:text-danger disabled:opacity-30"
                        title="删除"
                      >
                        <Trash2 size={10} />
                      </button>
                    </div>
                  </div>

                  {/* Description */}
                  <p className="text-[10px] text-fg-muted mt-1">{c.description}</p>

                  {/* Status message */}
                  {c.status_message && (
                    <p
                      className={`text-[10px] mt-0.5 truncate ${
                        c.status === 'error' ? 'text-danger' : 'text-fg-secondary'
                      }`}
                      title={c.status_message}
                    >
                      {c.status_message}
                    </p>
                  )}
                  {!c.status_message && c.last_error && (
                    <p className="text-[10px] mt-0.5 truncate text-danger" title={c.last_error}>
                      {c.last_error}
                    </p>
                  )}

                  {/* Edit area */}
                  {editing?.connectorName === c.name && c.config_schema?.properties ? (
                    <div className="mt-2 space-y-1.5">
                      {Object.entries(c.config_schema.properties).map(([key, prop]: [string, any]) => {
                        const isSensitive = prop.sensitive;
                        const show = editing.showValue[key] ?? !isSensitive;
                        const stored = c.config?.[key];
                        const masked = isSensitive && stored && typeof stored === 'object' ? stored.masked : '';
                        const enumOptions = Array.isArray(prop.enum) ? prop.enum : [];
                        const enumLabels = prop.enumLabels || {};
                        const isBoolean = prop.type === 'boolean';
                        return (
                          <div key={key}>
                            <label className="text-[10px] text-fg-secondary block font-medium">
                              {prop.label || key}
                            </label>
                            <div className="flex gap-1 mt-0.5">
                              {isBoolean ? (
                                <label className="flex flex-1 items-center gap-2 text-[11px] text-fg-secondary bg-surface border border-border rounded px-2 py-1">
                                  <input
                                    type="checkbox"
                                    checked={Boolean(editing.fields[key])}
                                    onChange={(e) => updateField(key, e.target.checked)}
                                    className="h-3 w-3 accent-accent"
                                  />
                                  <span>{prop.description || prop.label || key}</span>
                                </label>
                              ) : enumOptions.length > 0 ? (
                                <select
                                  value={String(editing.fields[key] || prop.default || enumOptions[0] || '')}
                                  onChange={(e) => updateField(key, e.target.value)}
                                  className="flex-1 text-xs bg-surface border border-border rounded px-2 py-1 outline-none text-fg focus:border-accent focus:ring-1 focus:ring-accent/30"
                                >
                                  {enumOptions.map((option: string) => (
                                    <option key={option} value={option}>
                                      {enumLabels[option] || option}
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                <input
                                  type={show ? 'text' : 'password'}
                                  value={String(editing.fields[key] || '')}
                                  onChange={(e) => updateField(key, e.target.value)}
                                  placeholder={masked || prop.description || `输入 ${prop.label || key}...`}
                                  className="flex-1 text-xs bg-surface border border-border rounded px-2 py-1 outline-none text-fg focus:border-accent focus:ring-1 focus:ring-accent/30"
                                />
                              )}
                              {isSensitive && (
                                <button
                                  onClick={() => toggleShow(key)}
                                  className="px-1.5 text-fg-secondary hover:text-fg bg-surface border border-border rounded hover:bg-surface-hover"
                                  title={show ? '隐藏' : '显示'}
                                >
                                  {show ? <EyeOff size={12} /> : <Eye size={12} />}
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                      <div className="flex gap-1 pt-1">
                        <button
                          onClick={handleSave}
                          title="Save connector config"
                          disabled={operatingId === c.name}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-accent/10 text-accent border border-accent/25 hover:bg-accent/15 disabled:opacity-50"
                        >
                          <Save size={10} />
                          保存
                        </button>
                        {hasNotificationConfig(c) && (
                          <button
                            onClick={() => handleTestMessage(c.name)}
                            disabled={testingId === c.name || operatingId === c.name}
                            className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-success/10 text-success border border-success/25 hover:bg-success/15 disabled:opacity-50"
                          >
                            {testingId === c.name ? <Loader2 size={10} className="animate-spin" /> : <Send size={10} />}
                            Test message
                          </button>
                        )}
                        <button
                          onClick={cancelEdit}
                          className="px-2 py-1 rounded text-[10px] text-fg-secondary hover:text-fg hover:bg-surface-hover"
                        >
                          取消
                        </button>
                      </div>
                      {testStatus[c.name] && (
                        <p className="text-[10px] text-success">{testStatus[c.name]}</p>
                      )}
                    </div>
                  ) : (
                    hasConfig(c) && (
                      <div className="mt-2">
                        <button
                          onClick={() => startEdit(c)}
                          title="Configure connector"
                          className="inline-flex items-center px-2 py-1 rounded border border-accent/25 bg-accent/10 text-[10px] font-medium text-accent hover:bg-accent/15 hover:border-accent/40 focus:outline-none focus:ring-2 focus:ring-accent/30"
                        >
                          配置凭据
                        </button>
                      </div>
                    )
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
