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
      <div className="px-3 py-2 border-b border-gray-700 flex items-center gap-2">
        <Film size={14} className="text-purple-400" />
        <span className="font-semibold text-gray-200">工作流</span>
        {loading && <Loader2 size={14} className="animate-spin text-gray-400" />}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {workflows.length === 0 ? (
          <div className="text-xs text-gray-500 text-center mt-4">暂无工作流</div>
        ) : (
          <div className="space-y-2">
            {workflows.map((wf) => (
              <div key={wf.id} className="bg-gray-800 rounded overflow-hidden">
                {/* Header */}
                <div
                  className="flex items-center justify-between px-2 py-1.5 cursor-pointer hover:bg-gray-750"
                  onClick={() => toggleExpand(wf.id)}
                >
                  <div className="flex items-center gap-1 flex-1 min-w-0">
                    {expandedId === wf.id ? (
                      <ChevronDown size={12} className="text-gray-400" />
                    ) : (
                      <ChevronRight size={12} className="text-gray-400" />
                    )}
                    <span className="text-xs text-gray-200 truncate">{wf.name}</span>
                    <span className="text-[10px] text-gray-500">({wf.steps.length} 步)</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRun(wf);
                      }}
                      disabled={runningId === wf.id}
                      className="px-1.5 py-0.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 rounded text-white text-[10px]"
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
                      className="px-1 py-0.5 text-red-400 hover:text-red-300"
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                </div>

                {/* Expanded */}
                {expandedId === wf.id && (
                  <div className="px-3 pb-2 border-t border-gray-700">
                    {wf.description && (
                      <div className="text-[10px] text-gray-500 mt-1">{wf.description}</div>
                    )}
                    {/* Variables */}
                    {wf.variables.length > 0 && (
                      <div className="mt-2 space-y-1">
                        <div className="text-[10px] text-gray-400">变量</div>
                        {wf.variables.map((v) => (
                          <div key={v.name} className="flex gap-1">
                            <span className="text-[10px] text-gray-400 w-20 truncate">{v.name}</span>
                            <input
                              type="text"
                              value={variableInputs[wf.id]?.[v.name] || v.default || ''}
                              onChange={(e) => updateVar(wf.id, v.name, e.target.value)}
                              placeholder={v.description || v.default}
                              className="flex-1 bg-gray-900 border border-gray-600 rounded px-1 py-0.5 text-[10px] text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500"
                            />
                          </div>
                        ))}
                      </div>
                    )}
                    {/* Steps */}
                    <div className="mt-2 space-y-1">
                      <div className="text-[10px] text-gray-400">步骤</div>
                      {wf.steps.map((step, i) => (
                        <div key={step.step_id} className="text-[10px] text-gray-300 bg-gray-900 rounded px-1.5 py-0.5">
                          {i + 1}. {step.tool_name}
                          {step.param_args && Object.keys(step.param_args).length > 0 && (
                            <span className="text-gray-500 ml-1">(参数化)</span>
                          )}
                        </div>
                      ))}
                    </div>
                    {/* Run result */}
                    {runResults[wf.id] && (
                      <div className="mt-2 p-1.5 bg-gray-900 rounded text-[10px] text-gray-300 whitespace-pre-wrap font-mono">
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
