import React, { useState } from 'react';
import { 
  Trash2, Terminal, Zap, Monitor, MousePointer, 
  Globe, FolderOpen, Command, Play, Square, Plus, MessageSquare, X
} from 'lucide-react';
import { ModelInfo } from '../types';

interface SidebarProps {
  models: ModelInfo[];
  currentModel: string;
  onModelChange: (model: string) => void;
  onClear: () => void;
  onToggleTerminal: () => void;
  onExecuteTool: (name: string, args: any) => void;
  isConnected: boolean;
  sessions?: {id: string; model_id: string; message_count: number}[];
  currentSession?: string;
  onNewSession?: () => void;
  onSwitchSession?: (id: string) => void;
  onDeleteSession?: (id: string) => void;
}

const QUICK_TOOLS = [
  { name: 'screenshot', icon: Monitor, label: '截图' },
  { name: 'get_screen_size', icon: Monitor, label: '屏幕尺寸' },
  { name: 'browser_navigate', icon: Globe, label: '打开浏览器', defaultArgs: { url: 'https://www.google.com' } },
  { name: 'browser_screenshot', icon: Globe, label: '网页截图' },
  { name: 'app_list_windows', icon: Monitor, label: '列出窗口' },
];

export const Sidebar: React.FC<SidebarProps> = ({
  models,
  currentModel,
  onModelChange,
  onClear,
  onToggleTerminal,
  onExecuteTool,
  isConnected,
  sessions = [],
  currentSession,
  onNewSession,
  onSwitchSession,
  onDeleteSession,
}) => {
  const [activeSection, setActiveSection] = useState<'tools' | 'settings' | 'sessions'>('tools');

  return (
    <div className="w-56 bg-gray-800 border-r border-gray-700 flex flex-col">
      {/* Logo / 状态 */}
      <div className="p-4 border-b border-gray-700">
        <div className="flex items-center gap-2 mb-2">
          <Zap className="w-5 h-5 text-agent-400" />
          <span className="font-bold text-sm">Agent Control</span>
        </div>
        <div className="text-xs text-gray-400">
          状态: {isConnected ? <span className="text-green-400">已连接</span> : <span className="text-red-400">未连接</span>}
        </div>
      </div>

      {/* 导航标签 */}
      <div className="flex border-b border-gray-700">
        <button
          onClick={() => setActiveSection('tools')}
          className={`flex-1 py-2 text-xs font-medium ${activeSection === 'tools' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'}`}
        >
          快捷工具
        </button>
        <button
          onClick={() => setActiveSection('sessions')}
          className={`flex-1 py-2 text-xs font-medium ${activeSection === 'sessions' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'}`}
        >
          会话
        </button>
        <button
          onClick={() => setActiveSection('settings')}
          className={`flex-1 py-2 text-xs font-medium ${activeSection === 'settings' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'}`}
        >
          设置
        </button>
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto p-3">
        {activeSection === 'tools' && (
          <div className="space-y-1">
            <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">桌面操控</div>
            {QUICK_TOOLS.map(tool => (
              <button
                key={tool.name}
                onClick={() => onExecuteTool(tool.name, tool.defaultArgs || {})}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-gray-300 hover:bg-gray-700 transition-colors"
              >
                <tool.icon className="w-3.5 h-3.5" />
                {tool.label}
              </button>
            ))}
          </div>
        )}

        {activeSection === 'sessions' && (
          <div className="space-y-2">
            <button
              onClick={onNewSession}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs bg-agent-700/30 text-agent-300 hover:bg-agent-700/50 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              新建会话
            </button>
            <div className="text-xs text-gray-500 uppercase tracking-wider mt-2">历史会话</div>
            {sessions.length === 0 && (
              <div className="text-xs text-gray-500 text-center py-4">暂无历史会话</div>
            )}
            {sessions.map(s => (
              <div
                key={s.id}
                className={`flex items-center justify-between px-2 py-1.5 rounded text-xs cursor-pointer ${
                  s.id === currentSession ? 'bg-gray-700 text-white' : 'text-gray-300 hover:bg-gray-700'
                }`}
              >
                <div className="flex items-center gap-2 flex-1 min-w-0" onClick={() => onSwitchSession?.(s.id)}>
                  <MessageSquare className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate">{s.id.replace('session_', '')}</span>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); onDeleteSession?.(s.id); }}
                  className="text-gray-500 hover:text-red-400 ml-1"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {activeSection === 'settings' && (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-gray-400 block mb-1">模型</label>
              <select
                value={currentModel}
                onChange={(e) => onModelChange(e.target.value)}
                className="w-full text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1.5 outline-none"
              >
                {models.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">提供商</label>
              <div className="text-xs text-gray-300">
                {models.find(m => m.id === currentModel)?.provider || '-'}
              </div>
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">视觉支持</label>
              <div className="text-xs text-gray-300">
                {models.find(m => m.id === currentModel)?.vision ? '✅ 支持' : '❌ 不支持'}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 底部操作 */}
      <div className="p-3 border-t border-gray-700 space-y-1">
        <button
          onClick={onToggleTerminal}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-gray-300 hover:bg-gray-700 transition-colors"
        >
          <Terminal className="w-3.5 h-3.5" />
          切换终端面板
        </button>
        <button
          onClick={onClear}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-red-400 hover:bg-gray-700 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" />
          清空会话
        </button>
      </div>
    </div>
  );
};