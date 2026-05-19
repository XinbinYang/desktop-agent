import React, { useState, useEffect, useCallback } from 'react';
import { Play, Trash2, Loader2, Film, Square, ChevronDown, ChevronRight } from 'lucide-react';
import { WorkflowData } from '../types';
import { API_BASE } from '../config';

export function WorkflowPanel() {
  const [workflows, setWorkflows] = useState<WorkflowData[]>([]);
  const [loading, setLoading] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [runResults, setRunResults] = useState<Record<string, string>>({});
  const [variableInputs, setVariableInputs] = useState<Record<string, Record<string, string>>>({});

  const loadWorkflows = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/workflows`);
      const data = await res.json();
      setWorkflows(data.workflows || []);
    } catch (err) {
      console.error('Failed to load workflows:', err);
    }
  }, []);

  useEffect(() => {
    loadWorkflows();
  }, [loadWorkflows]);

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除此工作流吗？')) return;
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/workflows/${id}`, { method: 'DELETE' });
      await loadWorkflows();
    } catch (err) {
      console.error('Failed to delete workflow:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleRun = async (wf: WorkflowData) => {
    setRunningId(wf.id);
    setRunResults((prev) => ({ ...prev, [wf.id]: '' }));
    try {
      const vars = variableInputs[wf.id] || {};
      const res = await fetch(`${API_BASE}/api/workflows/${wf.id}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ variables: vars }),
      });
      const data = await res.json();
      const lines = (data.events || []).map((e: any) => {
        if (e.type === 'step_start') return `[${e.progress}] 执行 ${e.tool_name}...`;
        if (e.type === 'step_end') return e.error ? `  ✗ 错误: ${e.error}` : `  ✓ 完成`;
        if (e.type === 'completed') return '工作流执行完毕。';
        return '';
      });
      setRunResults((prev) => ({ ...prev, [wf.id]: lines.join('\n') }));
    } catch (err) {
      setRunResults((prev) => ({ ...prev, [wf.id]: `执行失败: ${err}` }));
    } finally {
      setRunningId(null);
    }
  };

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  const updateVar = (wfId: string, varName: string, value: string) => {
    setVariableInputs((prev) => ({
      ...prev,
      [wfId]: { ...(prev[wfId] || {}), [varName]: value },
    }));
  };

  return (
    <div className="h-full flex flex-col text-sm">
      {/* Header */}
      <div className="px-3 py-2 border-b border-border flex items-center gap-2">
        <Film size={14} className="text-accent" />
        <span className="font-semibold text-fg">工作流</span>
        {loading && <Loader2 size={14} className="animate-spin text-fg-secondary" />}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {workflows.length === 0 ? (
          <div className="text-xs text-fg-muted text-center mt-4">暂无工作流</div>
        ) : (
          <div className="space-y-2">
            {workflows.map((wf) => (
              <div key={wf.id} className="bg-surface rounded overflow-hidden">
                {/* Header */}
                <div
                  className="flex items-center justify-between px-2 py-1.5 cursor-pointer hover:bg-surface-hover"
                  onClick={() => toggleExpand(wf.id)}
                >
                  <div className="flex items-center gap-1 flex-1 min-w-0">
                    {expandedId === wf.id ? (
                      <ChevronDown size={12} className="text-fg-secondary" />
                    ) : (
                      <ChevronRight size={12} className="text-fg-secondary" />
                    )}
                    <span className="text-xs text-fg truncate">{wf.name}</span>
                    <span className="text-[10px] text-fg-muted">({wf.steps.length} 步)</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRun(wf);
                      }}
                      disabled={runningId === wf.id}
                      className="px-1.5 py-0.5 bg-accent/85 hover:bg-accent disabled:opacity-50 rounded text-fg-on-accent text-[10px]"
                    >
                      {runningId === wf.id ? (
                        <Loader2 size={10} className="animate-spin" />
                      ) : (
                        <Play size={10} />
                      )}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(wf.id);
                      }}
                      className="px-1 py-0.5 text-danger hover:text-danger/80"
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                </div>

                {/* Expanded */}
                {expandedId === wf.id && (
                  <div className="px-3 pb-2 border-t border-border">
                    {wf.description && (
                      <div className="text-[10px] text-fg-muted mt-1">{wf.description}</div>
                    )}
                    {/* Variables */}
                    {wf.variables.length > 0 && (
                      <div className="mt-2 space-y-1">
                        <div className="text-[10px] text-fg-secondary">变量</div>
                        {wf.variables.map((v) => (
                          <div key={v.name} className="flex gap-1">
                            <span className="text-[10px] text-fg-secondary w-20 truncate">{v.name}</span>
                            <input
                              type="text"
                              value={variableInputs[wf.id]?.[v.name] || v.default || ''}
                              onChange={(e) => updateVar(wf.id, v.name, e.target.value)}
                              placeholder={v.description || v.default}
                              className="flex-1 bg-app border border-border-subtle rounded px-1 py-0.5 text-[10px] text-fg placeholder-fg-muted focus:outline-none focus:border-accent"
                            />
                          </div>
                        ))}
                      </div>
                    )}
                    {/* Steps */}
                    <div className="mt-2 space-y-1">
                      <div className="text-[10px] text-fg-secondary">步骤</div>
                      {wf.steps.map((step, i) => (
                        <div key={step.step_id} className="text-[10px] text-fg-secondary bg-app rounded px-1.5 py-0.5">
                          {i + 1}. {step.tool_name}
                          {step.param_args && Object.keys(step.param_args).length > 0 && (
                            <span className="text-fg-muted ml-1">(参数化)</span>
                          )}
                        </div>
                      ))}
                    </div>
                    {/* Run result */}
                    {runResults[wf.id] && (
                      <div className="mt-2 p-1.5 bg-app rounded text-[10px] text-fg-secondary whitespace-pre-wrap font-mono">
                        {runResults[wf.id]}
                      </div>
                    )}
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
