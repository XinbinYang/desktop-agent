import React, { useState, useEffect } from 'react';
import {
  X, Plus, Trash2, Edit3, Save, Eye, EyeOff, Settings, Wifi,
} from 'lucide-react';
import { ModelInfo, ProviderSettings, AppSettings, SettingsResponse } from '../types';
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
  return PROVIDER_COLORS[name] || 'bg-gray-500';
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
    models: p.models.map(m => ({ ...m })),
    showKey: false,
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

  useEffect(() => {
    if (isOpen) fetchSettings();
  }, [isOpen]);

  const fetchSettings = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/settings`);
      const data: SettingsResponse = await res.json();
      setSettings(data);
      setGeneralForm({ ...data.settings });
      setEditingProvider(null);
      setProviderForm(null);
      setIsCreating(false);
      setTestResult(null);
      setError('');
    } catch (e) {
      setError('Failed to load settings');
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
  };

  const saveProviderForm = async (): Promise<boolean> => {
    if (!providerForm) return true;
    if (!providerForm.name.trim()) { setError('Provider 名称不能为空'); return false; }
    if (!providerForm.base_url.trim()) { setError('Base URL 不能为空'); return false; }

    const body = {
      base_url: providerForm.base_url.trim(),
      api_key: providerForm.keyDirty ? providerForm.api_key.trim() : '',
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
      const res = await fetch(`${API_BASE}/api/providers/${encodeURIComponent(editingProvider)}`, {
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

  if (!isOpen) return null;

  const allProviderNames = settings ? Object.keys(settings.providers) : [];
  const defaultProvider = settings?.settings.default_provider || '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700 shrink-0">
          <div className="flex items-center gap-2">
            <Settings className="w-4 h-4 text-gray-400" />
            <h2 className="text-sm font-bold text-white">设置</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
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
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                全局设置
              </h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-400 block mb-1">默认模型</label>
                  <select
                    value={generalForm.default_model}
                    onChange={(e) => setGeneralForm({ ...generalForm, default_model: e.target.value })}
                    className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-gray-100"
                  >
                    {models.map(m => (
                      <option key={m.id} value={m.id}>{m.name} ({m.provider})</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-gray-400 block mb-1">默认 Provider</label>
                  <select
                    value={generalForm.default_provider}
                    onChange={(e) => setGeneralForm({ ...generalForm, default_provider: e.target.value })}
                    className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-gray-100"
                  >
                    {allProviderNames.map(p => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-gray-400 block mb-1">最大迭代次数</label>
                  <input
                    type="number"
                    min={1}
                    max={200}
                    value={generalForm.max_iterations}
                    onChange={(e) => setGeneralForm({ ...generalForm, max_iterations: parseInt(e.target.value) || 50 })}
                    className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-gray-100"
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
                    <span className="text-xs text-gray-400">自动批准</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={generalForm.screenshot_on_step}
                      onChange={(e) => setGeneralForm({ ...generalForm, screenshot_on_step: e.target.checked })}
                      className="rounded"
                    />
                    <span className="text-xs text-gray-400">每步截图</span>
                  </label>
                </div>
                <div className="col-span-2">
                  <label className="text-xs text-gray-400 block mb-1">权限模式</label>
                  <select
                    value={generalForm.sandbox_mode || 'sandbox'}
                    onChange={(e) => setGeneralForm({ ...generalForm, sandbox_mode: e.target.value })}
                    className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-gray-100"
                  >
                    <option value="sandbox">沙箱模式（限制在项目目录）</option>
                    <option value="unrestricted">无限制模式（可访问任意文件和命令）</option>
                  </select>
                  <div className="text-[10px] text-gray-500 mt-1">
                    无限制模式下 Agent 可以读写任意文件并执行任意命令，请谨慎使用。
                  </div>
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
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
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
              <div className="mb-3 p-3 rounded bg-gray-700/50 border border-gray-600 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-200">
                    {isCreating ? '新建 Provider' : `编辑 ${editingProvider}`}
                  </span>
                  <button onClick={cancelEditProvider} className="text-gray-400 hover:text-white">
                    <X className="w-3 h-3" />
                  </button>
                </div>

                <div>
                  <label className="text-xs text-gray-400 block mb-1">名称</label>
                  <input
                    value={providerForm.name}
                    onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })}
                    disabled={!isCreating}
                    placeholder="如: openai"
                    className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none disabled:opacity-50 text-gray-100"
                  />
                </div>

                <div>
                  <label className="text-xs text-gray-400 block mb-1">Base URL</label>
                  <input
                    value={providerForm.base_url}
                    onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })}
                    className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-gray-100 font-mono"
                  />
                </div>

                <div>
                  <label className="text-xs text-gray-400 block mb-1">API Key</label>
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
                      className="flex-1 text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-gray-100 font-mono"
                    />
                    <button
                      onClick={() => setProviderForm({ ...providerForm, showKey: !providerForm.showKey })}
                      className="px-2 text-gray-400 hover:text-white bg-gray-700 border border-gray-600 rounded"
                      title={providerForm.showKey ? '隐藏' : '显示'}
                    >
                      {providerForm.showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                </div>

                {/* 模型列表 */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs text-gray-400">模型列表</label>
                    <button
                      onClick={addModel}
                      className="p-0.5 text-gray-400 hover:text-accent"
                      title="添加模型"
                    >
                      <Plus className="w-3 h-3" />
                    </button>
                  </div>
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {providerForm.models.map((m, i) => (
                      <div
                        key={i}
                        className="grid grid-cols-[1fr_1fr_80px_45px_24px] gap-1 items-center"
                      >
                        <input
                          value={m.id}
                          onChange={(e) => updateModel(i, 'id', e.target.value)}
                          placeholder="model id"
                          className="text-[10px] bg-gray-700 border border-gray-600 rounded px-1.5 py-1 outline-none text-gray-100 font-mono"
                        />
                        <input
                          value={m.name}
                          onChange={(e) => updateModel(i, 'name', e.target.value)}
                          placeholder="display name"
                          className="text-[10px] bg-gray-700 border border-gray-600 rounded px-1.5 py-1 outline-none text-gray-100"
                        />
                        <input
                          type="number"
                          value={m.context}
                          onChange={(e) => updateModel(i, 'context', parseInt(e.target.value) || 0)}
                          placeholder="context"
                          className="text-[10px] bg-gray-700 border border-gray-600 rounded px-1.5 py-1 outline-none text-gray-100"
                        />
                        <label className="flex items-center gap-0.5 text-[10px] text-gray-400 cursor-pointer">
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
                          className="p-0.5 text-gray-500 hover:text-red-400"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                    {providerForm.models.length === 0 && (
                      <div className="text-xs text-gray-500 text-center py-2">暂无模型，点击 + 添加</div>
                    )}
                  </div>
                </div>

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
                      <span className="ml-2 text-gray-400">({testResult.model_count} models)</span>
                    )}
                  </div>
                )}

                <div className="flex gap-2">
                  <button
                    onClick={handleTestProvider}
                    disabled={testingProvider || saving || !providerForm.base_url.trim()}
                    title="Test connection"
                    className="flex items-center justify-center gap-1 px-3 py-1.5 rounded text-xs bg-gray-700 text-gray-200 hover:bg-gray-600 transition-colors disabled:opacity-50"
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
                    className="px-3 py-1.5 rounded text-xs text-gray-300 hover:bg-gray-700 transition-colors"
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
                      className="flex items-center gap-3 px-3 py-2.5 rounded bg-gray-700/50 border border-gray-600 hover:border-gray-500 transition-colors"
                    >
                      {getProviderIcon(pname)}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-medium text-gray-200">{pname}</span>
                          {isDefault && (
                            <span className="text-[10px] bg-accent/12 text-accent px-1 py-0.5 rounded border border-accent/25">
                              默认
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-gray-500 font-mono truncate">{p.api_key_masked}</div>
                      </div>
                      <div className="text-[10px] text-gray-400 hidden sm:block truncate max-w-[120px]">
                        {p.base_url}
                      </div>
                      <span className="text-[10px] text-gray-600 bg-gray-800 px-1.5 py-0.5 rounded">
                        {p.models.length} 个模型
                      </span>
                      <button
                        onClick={() => startEditProvider(pname)}
                        className="p-1 text-gray-400 hover:text-white"
                        title="编辑"
                      >
                        <Edit3 className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => handleDeleteProvider(pname)}
                        disabled={isDefault || isDeleting}
                        className="p-1 text-gray-400 hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed"
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
        <div className="flex items-center justify-between p-4 border-t border-gray-700 shrink-0">
          <span className="text-xs text-gray-500">
            当前模型: {models.find(m => m.id === currentModel)?.name || currentModel}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded text-xs text-gray-300 hover:bg-gray-700 transition-colors"
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
