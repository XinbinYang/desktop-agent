import React, { useState } from 'react';
import { X, FolderOpen, GitBranch } from 'lucide-react';
import { API_BASE } from '../config';

interface ProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onProjectCreated: (project: any) => void;
}

const TEMPLATES = [
  { id: 'empty', name: '空项目', description: '仅包含 README 和 .gitignore' },
  { id: 'python', name: 'Python', description: 'src/, tests/, requirements.txt, main.py' },
  { id: 'react', name: 'React', description: 'Vite + React 项目结构' },
  { id: 'nodejs', name: 'Node.js', description: '简单的 Node.js 项目' },
];

export const ProjectModal: React.FC<ProjectModalProps> = ({ isOpen, onClose, onProjectCreated }) => {
  const [activeTab, setActiveTab] = useState<'new' | 'clone'>('new');
  const [parentPath, setParentPath] = useState('');
  const [projectName, setProjectName] = useState('');
  const [template, setTemplate] = useState('empty');
  const [cloneUrl, setCloneUrl] = useState('');
  const [clonePath, setClonePath] = useState('');
  const [cloneToken, setCloneToken] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const handleSelectFolder = async () => {
    const result = await window.electronAPI.selectFolder();
    if (result) {
      if (activeTab === 'new') {
        setParentPath(result);
      } else {
        setClonePath(result);
      }
    }
  };

  const handleCreate = async () => {
    if (!parentPath || !projectName) {
      setError('请填写所有必填字段');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/projects/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parent_path: parentPath, name: projectName, template }),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        onProjectCreated(data);
        onClose();
      }
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  };

  const handleClone = async () => {
    if (!cloneUrl || !clonePath) {
      setError('请填写所有必填字段');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/projects/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: cloneUrl, path: clonePath, token: cloneToken || undefined }),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        // 打开克隆的项目
        onProjectCreated(data);
        onClose();
      }
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg shadow-xl w-[480px] max-w-[90vw]">
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <h3 className="text-sm font-bold text-white">项目管理</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex border-b border-gray-700">
          <button
            onClick={() => { setActiveTab('new'); setError(''); }}
            className={`flex-1 py-2 text-xs font-medium ${activeTab === 'new' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'}`}
          >
            新建项目
          </button>
          <button
            onClick={() => { setActiveTab('clone'); setError(''); }}
            className={`flex-1 py-2 text-xs font-medium ${activeTab === 'clone' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'}`}
          >
            Clone 仓库
          </button>
        </div>

        <div className="p-4 space-y-3">
          {activeTab === 'new' ? (
            <>
              <div>
                <label className="text-xs text-gray-400 block mb-1">父目录</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={parentPath}
                    onChange={(e) => setParentPath(e.target.value)}
                    placeholder="选择或输入父目录路径"
                    className="flex-1 text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-white"
                  />
                  <button
                    onClick={handleSelectFolder}
                    className="px-2 py-1.5 rounded text-xs bg-gray-700 border border-gray-600 text-gray-300 hover:bg-gray-600"
                  >
                    <FolderOpen className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">项目名称</label>
                <input
                  type="text"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="my-project"
                  className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-white"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">模板</label>
                <div className="grid grid-cols-2 gap-2">
                  {TEMPLATES.map(t => (
                    <button
                      key={t.id}
                      onClick={() => setTemplate(t.id)}
                      className={`text-left p-2 rounded text-xs border transition-colors ${
                        template === t.id
                          ? 'border-accent bg-accent/10 text-white'
                          : 'border-gray-600 text-gray-300 hover:border-gray-500'
                      }`}
                    >
                      <div className="font-medium">{t.name}</div>
                      <div className="text-[10px] text-gray-500 mt-0.5">{t.description}</div>
                    </button>
                  ))}
                </div>
              </div>
              <button
                onClick={handleCreate}
                disabled={loading}
                className="w-full py-2 rounded text-xs bg-accent/85 text-white hover:bg-accent disabled:opacity-50 transition-colors"
              >
                {loading ? '创建中...' : '创建项目'}
              </button>
            </>
          ) : (
            <>
              <div>
                <label className="text-xs text-gray-400 block mb-1">仓库 URL</label>
                <input
                  type="text"
                  value={cloneUrl}
                  onChange={(e) => setCloneUrl(e.target.value)}
                  placeholder="https://github.com/user/repo.git"
                  className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-white"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">目标目录</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={clonePath}
                    onChange={(e) => setClonePath(e.target.value)}
                    placeholder="选择或输入目标目录"
                    className="flex-1 text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-white"
                  />
                  <button
                    onClick={handleSelectFolder}
                    className="px-2 py-1.5 rounded text-xs bg-gray-700 border border-gray-600 text-gray-300 hover:bg-gray-600"
                  >
                    <FolderOpen className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-400 block mb-1">Token（私有仓库可选）</label>
                <input
                  type="password"
                  value={cloneToken}
                  onChange={(e) => setCloneToken(e.target.value)}
                  placeholder="ghp_xxxxxxxxxxxx"
                  className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none text-white"
                />
              </div>
              <button
                onClick={handleClone}
                disabled={loading}
                className="w-full py-2 rounded text-xs bg-accent/85 text-white hover:bg-accent disabled:opacity-50 transition-colors"
              >
                {loading ? '克隆中...' : 'Clone 仓库'}
              </button>
            </>
          )}
          {error && (
            <div className="text-xs text-red-400 bg-red-900/20 rounded px-2 py-1">
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
