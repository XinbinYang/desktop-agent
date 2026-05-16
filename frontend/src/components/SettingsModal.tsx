import React, { useState, useEffect, useMemo } from 'react';
import {
  X, Plus, Trash2, Edit3, Save, Eye, EyeOff, Settings, Wifi, Download,
} from 'lucide-react';
import { ModelInfo, ProviderSettings, AppSettings, SettingsResponse, SuggestedModel } from '../types';
import { API_BASE } from '../config';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  models: ModelInfo[];
  currentModel: string;
  onSettingsChanged: () => void;
}

const PROVIDER_COLORS: Record<string, string> = {
  openai: 'bg-green-600',
  anthropic: 'bg-purple-600',
  kimi: 'bg-blue-600',
  local: 'bg-orange-500',
};

function providerColor(name: string): string {
  return PROVIDER_COLORS[name] || 'bg-surface-hover';
}

function providerInitial(name: string): string {
  return name.charAt(0).toUpperCase();
}

function getProviderIcon(name: string): React.ReactNode {
  const color = providerColor(name);
  const initial = providerInitial(name);
  return (
    <div className={`w-7 h-7 rounded-full ${color} flex items-center justify-center text-white text-xs font-bold shrink-0`}>
      {initial}
    </div>
  );
}

interface EditableProvider {
  name: string;
  base_url: string;
  api_key: string;
  litellm_provider: string;
  models: ModelInfo[];
  showKey: boolean;
  keyDirty: boolean;
}

interface ProviderTestResult {
  ok: boolean;
  message: string;
  status_code?: number;
  model_found?: boolean | null;
  model_count?: number;
}

function providerToEditable(p: ProviderSettings): EditableProvider {
  return {
    name: p.name,
    base_url: p.base_url,
    api_key: p.api_key_masked,
    litellm_provider: p.litellm_provider || '',
    models: p.models.map(m => ({ ...m })),
    showKey: true,
    keyDirty: false,
  };
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen, onClose, models, currentModel, onSettingsChanged,
}) => {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [generalForm, setGeneralForm] = useState<AppSettings | null>(null);
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [providerForm, setProviderForm] = useState<EditableProvider | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [deletingProvider, setDeletingProvider] = useState<string | null>(null);
  const [testingProvider, setTestingProvider] = useState(false);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [fetchedModels, setFetchedModels] = useState<SuggestedModel[]>([]);
  const [pickerSelection, setPickerSelection] = useState<Record<string, boolean>>({});
  const [pickerSearch, setPickerSearch] = useState('');

  useEffect(() => {
    if (isOpen) fetchSettings();
  }, [isOpen]);

  const fetchSettings = async () => {
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/settings`);
      const rawText = await res.text();
      let data: unknown;
      try {
        data = rawText ? JSON.parse(rawText) : {};
      } catch {
        setError(
          `加载设置失败：服务器返回非 JSON（HTTP ${res.status}）。请确认地址为 ${API_BASE} 且为本应用后端。`,
        );
        setSettings(null);
        setGeneralForm(null);
        return;
      }
      if (!res.ok) {
        const d = data as { detail?: unknown; error?: unknown };
        const detail =
          typeof d.detail === 'string'
            ? d.detail
            : Array.isArray(d.detail)
              ? JSON.stringify(d.detail)
              : typeof d.error === 'string'
                ? d.error
                : `HTTP ${res.status}`;
        setError(
          `加载设置失败：${detail}。若启用了本地令牌（DESKTOP_AGENT_AUTH_TOKEN），请确认应用已配置 X-Desktop-Agent-Token。`,
        );
        setSettings(null);
        setGeneralForm(null);
        return;
      }
      if (
        typeof data !== 'object' ||
        data === null ||
        typeof (data as SettingsResponse).providers !== 'object' ||
        (data as SettingsResponse).providers === null ||
        typeof (data as SettingsResponse).settings !== 'object' ||
        (data as SettingsResponse).settings === null
      ) {
        setError('加载设置失败：返回数据缺少 providers 或 settings。');
        setSettings(null);
        setGeneralForm(null);
        return;
      }
      const ok = data as SettingsResponse;
      setSettings(ok);
      setGeneralForm({ ...ok.settings });
      setEditingProvider(null);
      setProviderForm(null);
      setIsCreating(false);
      setTestResult(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      const looksLikeNetwork =
        e instanceof TypeError ||
        /failed to fetch|networkerror|network error|load failed|aborted/i.test(msg);
      setError(
        looksLikeNetwork
          ? `无法连接后端 ${API_BASE}。请先在本机启动后端（例如 backend 目录运行 python start.py，或使用仓库根目录的 start-all.ps1），再打开设置。`
          : `加载设置失败：${msg}`,
      );
      setSettings(null);
      setGeneralForm(null);
    }
  };

  const startEditProvider = (name: string) => {
    if (!settings) return;
    const p = settings.providers[name];
    if (!p) return;
    setIsCreating(false);
    setEditingProvider(name);
    setTestResult(null);
    setProviderForm(providerToEditable(p));
  };

  const startCreateProvider = () => {
    setIsCreating(true);
    setEditingProvider(null);
    setTestResult(null);
    setProviderForm({
      name: '',
      base_url: 'https://api.openai.com/v1',
      api_key: '',
      litellm_provider: '',
      models: [],
      showKey: true,
      keyDirty: true,
    });
  };

  const cancelEditProvider = () => {
    setEditingProvider(null);
    setProviderForm(null);
    setIsCreating(false);
    setTestResult(null);
    setModelPickerOpen(false);
    setFetchedModels([]);
    setPickerSelection({});
    setPickerSearch('');
  };

  const saveProviderForm = async (): Promise<boolean> => {
    if (!providerForm) return true;
    if (!providerForm.name.trim()) { setError('Provider 名称不能为空'); return false; }
    if (!providerForm.base_url.trim()) { setError('Base URL 不能为空'); return false; }

    const body = {
      base_url: providerForm.base_url.trim(),
      api_key: providerForm.keyDirty ? providerForm.api_key.trim() : '',
      litellm_provider: providerForm.litellm_provider,
      models: providerForm.models,
    };

    if (isCreating) {
      const res = await fetch(`${API_BASE}/api/providers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: providerForm.name.trim(), ...body }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '创建失败');
      }
    } else if (editingProvider) {
      // If name changed, rename the provider first
      const newName = providerForm.name.trim();
      if (newName !== editingProvider) {
        const renameRes = await fetch(`${API_BASE}/api/providers/${encodeURIComponent(editingProvider)}/rename`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ new_name: newName }),
        });
        if (!renameRes.ok) {
          const err = await renameRes.json();
          throw new Error(err.detail || '重命名失败');
        }
        // Update model provider references in the form payload
        body.models = body.models.map((m: any) => ({ ...m, provider: newName }));
      }
      const res = await fetch(`${API_BASE}/api/providers/${encodeURIComponent(newName || editingProvider)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '更新失败');
      }
    }
    return true;
  };

  const handleSaveProvider = async () => {
    setSaving(true);
    setError('');
    try {
      const ok = await saveProviderForm();
      if (!ok) return;
      await fetch(`${API_BASE}/api/config/reload`, { method: 'POST' });
      await fetchSettings();
      onSettingsChanged();
    } catch (e: any) {
      setError(e.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTestProvider = async () => {
    if (!providerForm) return;
    if (!providerForm.base_url.trim()) { setError('Base URL 不能为空'); return; }

    setTestingProvider(true);
    setError('');
    setTestResult(null);

    try {
      const modelId = providerForm.models.find(m => m.id.trim())?.id.trim() || '';
      const res = await fetch(`${API_BASE}/api/providers/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_name: editingProvider || providerForm.name.trim() || null,
          base_url: providerForm.base_url.trim(),
          api_key: providerForm.keyDirty ? providerForm.api_key.trim() : '',
          model_id: modelId || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || '测试连接失败');
      }
      setTestResult(data);
    } catch (e: any) {
      setTestResult({ ok: false, message: e.message || '测试连接失败' });
    } finally {
      setTestingProvider(false);
    }
  };

  const handleDeleteProvider = async (name: string) => {
    setDeletingProvider(name);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/providers/${encodeURIComponent(name)}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '删除失败');
      }
      await fetch(`${API_BASE}/api/config/reload`, { method: 'POST' });
      await fetchSettings();
      onSettingsChanged();
    } catch (e: any) {
      setError(e.message || '删除失败');
    } finally {
      setDeletingProvider(null);
    }
  };

  const handleSaveGeneral = async () => {
    if (!generalForm) return;
    setSaving(true);
    setError('');
    try {
      await fetch(`${API_BASE}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(generalForm),
      });
      await fetch(`${API_BASE}/api/config/reload`, { method: 'POST' });
      onSettingsChanged();
    } catch (e: any) {
      setError(e.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAll = async () => {
    setSaving(true);
    setError('');
    try {
      if (providerForm) {
        const ok = await saveProviderForm();
        if (!ok) { setSaving(false); return; }
      }
      if (generalForm) {
        await fetch(`${API_BASE}/api/settings`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(generalForm),
        });
      }
      await fetch(`${API_BASE}/api/config/reload`, { method: 'POST' });
      onSettingsChanged();
      onClose();
    } catch (e: any) {
      setError(e.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const updateModel = (idx: number, field: keyof ModelInfo, value: any) => {
    if (!providerForm) return;
    const newModels = [...providerForm.models];
    newModels[idx] = { ...newModels[idx], [field]: value };
    setProviderForm({ ...providerForm, models: newModels });
  };

  const removeModel = (idx: number) => {
    if (!providerForm) return;
    setProviderForm({
      ...providerForm,
      models: providerForm.models.filter((_, i) => i !== idx),
    });
  };

  const addModel = () => {
    if (!providerForm) return;
    setProviderForm({
      ...providerForm,
      models: [
        ...providerForm.models,
        { id: '', name: '', provider: providerForm.name || 'custom', vision: false, context: 32000 },
      ],
    });
  };

  const handleFetchModels = async () => {
    if (!providerForm) return;
    if (!providerForm.base_url.trim()) { setError('Base URL 不能为空'); return; }

    setFetchingModels(true);
    setError('');
    setTestResult(null);

    try {
      const res = await fetch(`${API_BASE}/api/providers/fetch-models`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_name: editingProvider || providerForm.name.trim() || null,
          base_url: providerForm.base_url.trim(),
          api_key: providerForm.keyDirty ? providerForm.api_key.trim() : '',
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.message || data.detail || '拉取模型列表失败');
      }
      setFetchedModels(data.models || []);
      // Pre-select models not already in the form
      const existingIds = new Set(providerForm.models.map(m => m.id));
      const initialSelection: Record<string, boolean> = {};
      for (const m of data.models) {
        initialSelection[m.id] = existingIds.has(m.id);
      }
      setPickerSelection(initialSelection);
      setPickerSearch('');
      setModelPickerOpen(true);
    } catch (e: any) {
      setTestResult({ ok: false, message: e.message || '拉取失败' });
    } finally {
      setFetchingModels(false);
    }
  };

  const handleAddSelectedModels = () => {
    if (!providerForm) return;
    const existingIds = new Set(providerForm.models.map(m => m.id));
    const newModels = fetchedModels
      .filter(m => pickerSelection[m.id] && !existingIds.has(m.id))
      .map(m => ({
        id: m.id,
        name: m.suggested_name,
        provider: providerForm.name || 'custom',
        context: m.suggested_context,
        vision: m.vision,
      }));
    if (newModels.length === 0) return;
    setProviderForm({
      ...providerForm,
      models: [...providerForm.models, ...newModels],
    });
    setModelPickerOpen(false);
    setFetchedModels([]);
  };

  const existingModelIds = useMemo(() => {
    return new Set(providerForm?.models.map(m => m.id) || []);
  }, [providerForm?.models]);

  const filteredFetchedModels = useMemo(() => {
    if (!pickerSearch.trim()) return fetchedModels;
    const q = pickerSearch.toLowerCase();
    return fetchedModels.filter(m => m.id.toLowerCase().includes(q));
  }, [fetchedModels, pickerSearch]);

  if (!isOpen) return null;

  const allProviderNames =
    settings && typeof settings.providers === 'object' && settings.providers !== null
      ? Object.keys(settings.providers)
      : [];
  const defaultProvider = settings?.settings.default_provider || '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-surface rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            <Settings className="w-4 h-4 text-fg-secondary" />
            <h2 className="text-sm font-bold text-fg">设置</h2>
          </div>
          <button onClick={onClose} className="text-fg-secondary hover:text-fg">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {error && (
            <div className="px-3 py-2 rounded text-xs bg-red-900/30 border border-red-800 text-red-300">
              {error}
            </div>
          )}

          {/* 全局设置 */}
          {generalForm && (
            <section>
              <h3 className="text-xs font-semibold text-fg-secondary uppercase tracking-wider mb-3">
                全局设置
              </h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-fg-secondary block mb-1">默认模型</label>
                  <select
                    value={generalForm.default_model}
                    onChange={(e) => setGeneralForm({ ...generalForm, default_model: e.target.value })}
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                  >
                    {models.map(m => (
                      <option key={m.id} value={m.id}>{m.name} ({m.provider})</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-fg-secondary block mb-1">默认 Provider</label>
                  <select
                    value={generalForm.default_provider}
                    onChange={(e) => setGeneralForm({ ...generalForm, default_provider: e.target.value })}
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                  >
                    {allProviderNames.map(p => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-fg-secondary block mb-1">最大迭代次数</label>
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    value={generalForm.max_iterations}
                    onChange={(e) => setGeneralForm({ ...generalForm, max_iterations: parseInt(e.target.value) || 10000 })}
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                  />
                </div>
                <div className="flex flex-col gap-3 pt-1">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={generalForm.auto_approve}
                      onChange={(e) => setGeneralForm({ ...generalForm, auto_approve: e.target.checked })}
                      className="rounded"
                    />
                    <span className="text-xs text-fg-secondary">自动批准</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={generalForm.screenshot_on_step}
                      onChange={(e) => setGeneralForm({ ...generalForm, screenshot_on_step: e.target.checked })}
                      className="rounded"
                    />
                    <span className="text-xs text-fg-secondary">每步截图</span>
                  </label>
                </div>
                <div className="col-span-2">
                  <label className="text-xs text-fg-secondary block mb-1">权限模式</label>
                  <select
                    value={generalForm.sandbox_mode || 'sandbox'}
                    onChange={(e) => setGeneralForm({ ...generalForm, sandbox_mode: e.target.value })}
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                  >
                    <option value="sandbox">沙箱模式（限制在项目目录）</option>
                    <option value="unrestricted">无限制模式（可访问任意文件和命令）</option>
                  </select>
                  <div className="text-[10px] text-fg-muted mt-1">
                    无限制模式下 Agent 可以读写任意文件并执行任意命令，请谨慎使用。
                  </div>
                </div>
                <div>
                  <label className="text-xs text-fg-secondary block mb-1">默认 Thinking 强度</label>
                  <select
                    value={generalForm.thinking_intensity_default || 'medium'}
                    onChange={(e) =>
                      setGeneralForm({
                        ...generalForm,
                        thinking_intensity_default: e.target.value as AppSettings['thinking_intensity_default'],
                      })}
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                  <div className="text-[10px] text-fg-muted mt-1">
                    统一抽象：在支持的模型上影响推理预算或采样温度；不支持的提供商会自动降级。
                  </div>
                </div>
                <div>
                  <label className="text-xs text-fg-secondary block mb-1">多 Agent 协同</label>
                  <select
                    value={generalForm.collaboration_mode || 'serial'}
                    onChange={(e) =>
                      setGeneralForm({
                        ...generalForm,
                        collaboration_mode: e.target.value as AppSettings['collaboration_mode'],
                      })}
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                  >
                    <option value="serial">串行（默认）</option>
                    <option value="parallel">并行（按 parallel_group）</option>
                    <option value="hybrid">混合</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-fg-secondary block mb-1">最大并行子 Agent 数</label>
                  <input
                    type="number"
                    min={1}
                    max={16}
                    value={generalForm.max_parallel_agents ?? 3}
                    onChange={(e) =>
                      setGeneralForm({
                        ...generalForm,
                        max_parallel_agents: parseInt(e.target.value, 10) || 3,
                      })}
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                  />
                </div>
                <div className="col-span-2 flex flex-col gap-2 pt-1">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={generalForm.review_gate_enabled ?? true}
                      onChange={(e) =>
                        setGeneralForm({ ...generalForm, review_gate_enabled: e.target.checked })}
                      className="rounded"
                    />
                    <span className="text-xs text-fg-secondary">计划模式审查门（推荐开启）</span>
                  </label>
                </div>
              </div>
              <div className="mt-3">
                <button
                  onClick={handleSaveGeneral}
                  disabled={saving}
                  className="flex items-center gap-1 px-3 py-1.5 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors disabled:opacity-50"
                >
                  <Save className="w-3 h-3" />
                  保存全局设置
                </button>
              </div>
            </section>
          )}

          {/* Provider 设置 */}
          <section>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-fg-secondary uppercase tracking-wider">
                Providers
              </h3>
              <button
                onClick={startCreateProvider}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors"
              >
                <Plus className="w-3 h-3" />
                添加 Provider
              </button>
            </div>

            {/* 新建/编辑 Provider 表单 */}
            {providerForm && (
              <div className="mb-3 p-3 rounded bg-surface-alt/50 border border-border-subtle space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-fg">
                    {isCreating ? '新建 Provider' : `编辑 ${editingProvider}`}
                  </span>
                  <button onClick={cancelEditProvider} className="text-fg-secondary hover:text-fg">
                    <X className="w-3 h-3" />
                  </button>
                </div>

                <div>
                  <label className="text-xs text-fg-secondary block mb-1">名称</label>
                  <input
                    value={providerForm.name}
                    onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })}
                    placeholder="如: openai"
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                  />
                  {!isCreating && (
                    <div className="text-[10px] text-fg-muted mt-1">
                      修改名称会同步更新所有引用此 Provider 的模型与默认配置。
                    </div>
                  )}
                </div>

                <div>
                  <label className="text-xs text-fg-secondary block mb-1">Base URL</label>
                  <input
                    value={providerForm.base_url}
                    onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })}
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg font-mono"
                  />
                </div>

                <div>
                  <label className="text-xs text-fg-secondary block mb-1">
                    LiteLLM Provider 类型
                    <span className="text-fg-muted ml-1">（如 Provider 名称不是标准 LiteLLM 名称则需指定）</span>
                  </label>
                  <select
                    value={providerForm.litellm_provider}
                    onChange={(e) => setProviderForm({ ...providerForm, litellm_provider: e.target.value })}
                    className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                  >
                    <option value="">自动（使用 Provider 名称）</option>
                    <option value="openai">OpenAI / OpenAI 兼容</option>
                    <option value="deepseek">DeepSeek</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="openrouter">OpenRouter</option>
                    <option value="together_ai">Together AI</option>
                    <option value="groq">Groq</option>
                    <option value="azure">Azure</option>
                    <option value="vertex_ai">Vertex AI</option>
                    <option value="bedrock">Bedrock</option>
                    <option value="cohere">Cohere</option>
                    <option value="mistral">Mistral</option>
                    <option value="gemini">Gemini</option>
                  </select>
                </div>

                <div>
                  <label className="text-xs text-fg-secondary block mb-1">API Key</label>
                  <div className="flex gap-1">
                    <input
                      type={providerForm.showKey ? 'text' : 'password'}
                      value={providerForm.api_key}
                      onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value, keyDirty: true })}
                      onFocus={() => {
                        if (!providerForm.keyDirty) {
                          setProviderForm({ ...providerForm, api_key: '', keyDirty: true });
                        }
                      }}
                      placeholder="留空则保持不变；输入 ${ENV_VAR} 使用环境变量"
                      className="flex-1 text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg font-mono"
                    />
                    <button
                      onClick={() => setProviderForm({ ...providerForm, showKey: !providerForm.showKey })}
                      className="px-2 text-fg-secondary hover:text-fg bg-surface-alt border border-border-subtle rounded"
                      title={providerForm.showKey ? '隐藏' : '显示'}
                    >
                      {providerForm.showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                </div>

                {/* 模型列表 */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs text-fg-secondary">模型列表</label>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={handleFetchModels}
                        disabled={fetchingModels || !providerForm.base_url.trim()}
                        title="从 Provider 拉取模型列表"
                        className="p-0.5 text-fg-secondary hover:text-accent disabled:opacity-40"
                      >
                        <Download className={`w-3 h-3 ${fetchingModels ? 'animate-spin' : ''}`} />
                      </button>
                      <button
                        onClick={addModel}
                        className="p-0.5 text-fg-secondary hover:text-accent"
                        title="手动添加模型"
                      >
                        <Plus className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {providerForm.models.map((m, i) => (
                      <div
                        key={i}
                        className="grid grid-cols-[1.4fr_1.4fr_88px_56px_28px] gap-1 items-center"
                      >
                        <input
                          value={m.id}
                          onChange={(e) => updateModel(i, 'id', e.target.value)}
                          placeholder="model id"
                          className="chat-text-xs bg-surface-alt border border-border-subtle rounded px-1.5 py-1 outline-none text-fg font-mono"
                        />
                        <input
                          value={m.name}
                          onChange={(e) => updateModel(i, 'name', e.target.value)}
                          placeholder="display name"
                          className="chat-text-xs bg-surface-alt border border-border-subtle rounded px-1.5 py-1 outline-none text-fg"
                        />
                        <input
                          type="number"
                          value={m.context}
                          onChange={(e) => updateModel(i, 'context', parseInt(e.target.value) || 0)}
                          placeholder="context"
                          className="chat-text-xs bg-surface-alt border border-border-subtle rounded px-1.5 py-1 outline-none text-fg"
                        />
                        <label className="flex items-center gap-0.5 chat-text-xs text-fg-secondary cursor-pointer">
                          <input
                            type="checkbox"
                            checked={m.vision}
                            onChange={(e) => updateModel(i, 'vision', e.target.checked)}
                            className="w-3 h-3"
                          />
                          视觉
                        </label>
                        <button
                          onClick={() => removeModel(i)}
                          className="p-0.5 text-fg-muted hover:text-red-400"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                    {providerForm.models.length === 0 && (
                      <div className="text-xs text-fg-muted text-center py-2">暂无模型，点击 + 或从 Provider 拉取</div>
                    )}
                  </div>
                </div>

                {/* Model picker panel */}
                {modelPickerOpen && (
                  <div className="border border-border-subtle rounded bg-surface-alt/70 p-3 space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-fg">
                        选择要添加的模型 ({fetchedModels.length} 个可用)
                      </span>
                      <button
                        onClick={() => { setModelPickerOpen(false); setFetchedModels([]); }}
                        className="text-fg-secondary hover:text-fg"
                        title="关闭"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                    <input
                      value={pickerSearch}
                      onChange={(e) => setPickerSearch(e.target.value)}
                      placeholder="搜索模型..."
                      className="w-full chat-text-xs bg-surface border border-border-subtle rounded px-2 py-1.5 outline-none text-fg"
                    />
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => {
                          const allSelected: Record<string, boolean> = {};
                          filteredFetchedModels.forEach(m => { allSelected[m.id] = true; });
                          setPickerSelection(allSelected);
                        }}
                        className="text-[10px] text-accent hover:underline"
                      >
                        全选
                      </button>
                      <button
                        onClick={() => {
                          const cleared = { ...pickerSelection };
                          filteredFetchedModels.forEach(m => { cleared[m.id] = false; });
                          setPickerSelection(cleared);
                        }}
                        className="text-[10px] text-fg-secondary hover:underline"
                      >
                        反选
                      </button>
                    </div>
                    <div className="max-h-40 overflow-y-auto space-y-1">
                      {filteredFetchedModels.map(m => {
                        const alreadyAdded = existingModelIds.has(m.id);
                        const checked = pickerSelection[m.id] ?? false;
                        return (
                          <label
                            key={m.id}
                            className="flex items-center gap-2 px-2 py-1 rounded hover:bg-surface/50 cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={checked || alreadyAdded}
                              disabled={alreadyAdded}
                              onChange={() => {
                                setPickerSelection(prev => ({ ...prev, [m.id]: !prev[m.id] }));
                              }}
                              className="w-3 h-3"
                            />
                            <span className={`chat-text-xs flex-1 ${alreadyAdded ? 'text-fg-muted' : 'text-fg'}`}>
                              {m.id}
                            </span>
                            <span className="text-[10px] text-fg-muted">{m.suggested_name}</span>
                            <span className="text-[10px] text-fg-muted">{m.suggested_context}</span>
                            {m.vision && <span className="text-[10px] text-info">视觉</span>}
                            {alreadyAdded && <span className="text-[10px] text-fg-muted">已添加</span>}
                          </label>
                        );
                      })}
                      {filteredFetchedModels.length === 0 && (
                        <div className="text-xs text-fg-muted text-center py-2">无匹配模型</div>
                      )}
                    </div>
                    <button
                      onClick={handleAddSelectedModels}
                      className="w-full py-1.5 rounded text-xs bg-accent/85 hover:bg-accent text-white transition-colors"
                    >
                      添加 {Object.entries(pickerSelection).filter(([, v]) => v).length} 个模型
                    </button>
                  </div>
                )}

                {testResult && (
                  <div
                    className={`px-3 py-2 rounded text-xs border ${
                      testResult.ok
                        ? 'bg-green-900/20 border-green-800 text-green-300'
                        : 'bg-red-900/30 border-red-800 text-red-300'
                    }`}
                  >
                    {testResult.message}
                    {typeof testResult.model_count === 'number' && (
                      <span className="ml-2 text-fg-secondary">({testResult.model_count} models)</span>
                    )}
                  </div>
                )}

                <div className="flex gap-2">
                  <button
                    onClick={handleTestProvider}
                    disabled={testingProvider || saving || !providerForm.base_url.trim()}
                    title="Test connection"
                    className="flex items-center justify-center gap-1 px-3 py-1.5 rounded text-xs bg-surface-alt text-fg hover:bg-surface-hover transition-colors disabled:opacity-50"
                  >
                    <Wifi className="w-3 h-3" />
                    {testingProvider ? '测试中...' : '测试连接'}
                  </button>
                  <button
                    onClick={handleSaveProvider}
                    disabled={saving || !providerForm.name.trim() || !providerForm.base_url.trim()}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors disabled:opacity-50"
                  >
                    <Save className="w-3 h-3" />
                    {saving ? '保存中...' : '保存 Provider'}
                  </button>
                  <button
                    onClick={cancelEditProvider}
                    className="px-3 py-1.5 rounded text-xs text-fg-secondary hover:bg-surface-hover transition-colors"
                  >
                    取消
                  </button>
                </div>
              </div>
            )}

            {/* Provider 卡片列表 */}
            {settings && !providerForm && (
              <div className="space-y-2">
                {allProviderNames.map((pname) => {
                  const p = settings.providers[pname];
                  if (!p) return null;
                  const isDefault = defaultProvider === pname;
                  const isDeleting = deletingProvider === pname;
                  return (
                    <div
                      key={pname}
                      className="flex items-center gap-3 px-3 py-2.5 rounded bg-surface-alt/50 border border-border-subtle hover:border-border transition-colors"
                    >
                      {getProviderIcon(pname)}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-medium text-fg">{pname}</span>
                          {isDefault && (
                            <span className="text-[10px] bg-accent/12 text-accent px-1 py-0.5 rounded border border-accent/25">
                              默认
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-fg-muted font-mono truncate">{p.api_key_masked}</div>
                      </div>
                      <div className="text-[10px] text-fg-secondary hidden sm:block truncate max-w-[120px]">
                        {p.base_url}
                      </div>
                      <span className="text-[10px] text-fg-muted bg-surface px-1.5 py-0.5 rounded">
                        {p.models.length} 个模型
                      </span>
                      <button
                        onClick={() => startEditProvider(pname)}
                        className="p-1 text-fg-secondary hover:text-fg"
                        title="编辑"
                      >
                        <Edit3 className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => handleDeleteProvider(pname)}
                        disabled={isDefault || isDeleting}
                        className="p-1 text-fg-secondary hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed"
                        title={isDefault ? '不能删除默认 Provider' : '删除'}
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-border shrink-0">
          <span className="text-xs text-fg-muted">
            当前模型: {models.find(m => m.id === currentModel)?.name || currentModel}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded text-xs text-fg-secondary hover:bg-surface-hover transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleSaveAll}
              disabled={saving}
              className="flex items-center gap-1 px-4 py-1.5 rounded text-xs bg-accent/85 hover:bg-accent text-white transition-colors disabled:opacity-50"
            >
              {saving ? '保存中...' : '保存并关闭'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
