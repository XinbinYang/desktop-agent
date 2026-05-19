import React, { useState, useEffect } from 'react';
import { X, Plus, Trash2, Edit3, Save } from 'lucide-react';
import { saveRole, loadRoles, deleteRole } from '../lib/db';

interface CustomRole {
  id: string;
  name: string;
  description: string;
  prompt: string;
  createdAt: number;
}

interface RoleEditorProps {
  isOpen: boolean;
  onClose: () => void;
  onRolesChanged: () => void;
}

export const RoleEditor: React.FC<RoleEditorProps> = ({ isOpen, onClose, onRolesChanged }) => {
  const [roles, setRoles] = useState<CustomRole[]>([]);
  const [editing, setEditing] = useState<CustomRole | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    if (isOpen) refreshRoles();
  }, [isOpen]);

  const refreshRoles = async () => {
    const data = await loadRoles();
    setRoles(data);
  };

  const handleSave = async () => {
    if (!editing) return;
    if (!editing.id.trim() || !editing.name.trim() || !editing.prompt.trim()) return;
    await saveRole(editing);
    setEditing(null);
    setIsCreating(false);
    await refreshRoles();
    onRolesChanged();
  };

  const handleDelete = async (id: string) => {
    if (!confirm(`确定删除自定义角色 "${id}" 吗？`)) return;
    await deleteRole(id);
    await refreshRoles();
    onRolesChanged();
  };

  const startCreate = () => {
    setEditing({ id: '', name: '', description: '', prompt: '', createdAt: Date.now() });
    setIsCreating(true);
  };

  const startEdit = (role: CustomRole) => {
    setEditing({ ...role });
    setIsCreating(false);
  };

  const cancelEdit = () => {
    setEditing(null);
    setIsCreating(false);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-surface rounded-lg shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-sm font-bold text-fg">自定义角色</h2>
          <button onClick={onClose} className="text-fg-secondary hover:text-fg">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* 角色列表 */}
          {!editing && (
            <>
              <button
                onClick={startCreate}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                新建自定义角色
              </button>

              {roles.length === 0 && (
                <div className="text-xs text-fg-muted text-center py-4">暂无自定义角色</div>
              )}

              {roles.map((role) => (
                <div
                  key={role.id}
                  className="flex items-center justify-between px-3 py-2 rounded bg-surface-alt/50"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-fg truncate">{role.name}</div>
                    <div className="text-[10px] text-fg-muted truncate">{role.id}</div>
                  </div>
                  <div className="flex items-center gap-1 ml-2">
                    <button
                      onClick={() => startEdit(role)}
                      className="p-1 text-fg-secondary hover:text-fg"
                    >
                      <Edit3 className="w-3 h-3" />
                    </button>
                    <button
                      onClick={() => handleDelete(role.id)}
                      className="p-1 text-fg-secondary hover:text-danger"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              ))}
            </>
          )}

          {/* 编辑表单 */}
          {editing && (
            <div className="space-y-3">
              <div>
                <label className="text-xs text-fg-secondary block mb-1">角色 ID（英文标识）</label>
                <input
                  value={editing.id}
                  onChange={(e) => setEditing({ ...editing, id: e.target.value })}
                  disabled={!isCreating}
                  placeholder="如: my-custom-role"
                  className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg disabled:opacity-50 focus:border-accent"
                />
              </div>
              <div>
                <label className="text-xs text-fg-secondary block mb-1">名称</label>
                <input
                  value={editing.name}
                  onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                  placeholder="如: 我的自定义角色"
                  className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg focus:border-accent"
                />
              </div>
              <div>
                <label className="text-xs text-fg-secondary block mb-1">描述</label>
                <input
                  value={editing.description}
                  onChange={(e) => setEditing({ ...editing, description: e.target.value })}
                  placeholder="一句话描述角色定位"
                  className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg focus:border-accent"
                />
              </div>
              <div>
                <label className="text-xs text-fg-secondary block mb-1">
                  Prompt 模板
                  <span className="text-fg-muted ml-1">(可用 {'{{tools_desc}}'} 占位符注入工具列表)</span>
                </label>
                <textarea
                  value={editing.prompt}
                  onChange={(e) => setEditing({ ...editing, prompt: e.target.value })}
                  rows={12}
                  placeholder="你是一个..."
                  className="w-full text-xs bg-surface-alt border border-border-subtle rounded px-2 py-1.5 outline-none text-fg font-mono leading-relaxed resize-none focus:border-accent"
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleSave}
                  className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors"
                >
                  <Save className="w-3 h-3" />
                  保存
                </button>
                <button
                  onClick={cancelEdit}
                  className="px-3 py-1.5 rounded text-xs text-fg-secondary hover:bg-surface-hover transition-colors"
                >
                  取消
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
