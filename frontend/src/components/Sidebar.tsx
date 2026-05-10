import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Trash2, Zap, Monitor,
  Globe, Plus, MessageSquare, X,
  UserCog, Settings, BookOpen, Sun, Moon, Laptop
} from 'lucide-react';
import { RoleInfo, ProjectInfo, FileNode, SidebarSection } from '../types';
import { ProjectPanel } from './ProjectPanel';
import { useTheme } from '../hooks/useTheme';

interface SidebarProps {
  activeSection: SidebarSection;
  onSectionChange: (section: SidebarSection) => void;
  roles: RoleInfo[];
  currentRole: string;
  onRoleChange: (role: string) => void;
  onOpenRoleEditor: () => void;
  onOpenSettings: () => void;
  onClear: () => void;
  onExecuteTool: (name: string, args: any) => void;
  isConnected: boolean;
  sessions?: {id: string; model_id: string; message_count: number}[];
  currentSession?: string;
  onNewSession?: () => void;
  onSwitchSession?: (id: string) => void;
  onDeleteSession?: (id: string) => void;
  // 项目相关
  currentProject?: ProjectInfo | null;
  fileTree?: FileNode[];
  expandedPaths?: Set<string>;
  onTogglePath?: (path: string) => void;
  onSelectFile?: (path: string, type: 'file' | 'dir') => void;
  onOpenFolder?: () => void;
  onOpenProjectModal?: () => void;
  onCloseProject?: () => void;
  onRefreshTree?: () => void;
}

const QUICK_TOOLS = [
  { name: 'screenshot', icon: Monitor, label: 'Screenshot' },
  { name: 'get_screen_size', icon: Monitor, label: 'Screen Size' },
  { name: 'browser_navigate', icon: Globe, label: 'Open Browser', defaultArgs: { url: 'https://www.google.com' } },
  { name: 'browser_screenshot', icon: Globe, label: 'Web Screenshot' },
  { name: 'app_list_windows', icon: Monitor, label: 'List Windows' },
];

export const Sidebar: React.FC<SidebarProps> = ({
  activeSection,
  onSectionChange,
  roles,
  currentRole,
  onRoleChange,
  onOpenRoleEditor,
  onOpenSettings,
  onClear,
  onExecuteTool,
  isConnected,
  sessions = [],
  currentSession,
  onNewSession,
  onSwitchSession,
  onDeleteSession,
  // 项目
  currentProject,
  fileTree = [],
  expandedPaths = new Set(),
  onTogglePath,
  onSelectFile,
  onOpenFolder,
  onOpenProjectModal,
  onCloseProject,
  onRefreshTree,
}) => {
  const { theme, setTheme } = useTheme();
  const { t, i18n } = useTranslation();

  const changeLanguage = (lng: string) => {
    i18n.changeLanguage(lng);
    try { localStorage.setItem('desktop-agent-locale', lng); } catch { /* ignore */ }
  };

  return (
    <div className="w-56 bg-surface border-r border-border flex flex-col">
      {/* Logo / Status */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2 mb-2">
          <Zap className="w-5 h-5 text-accent" />
          <span className="font-bold text-sm">Agent Control</span>
        </div>
        <div className="text-xs text-fg-muted">
          Status: {isConnected ? <span className="text-success">Connected</span> : <span className="text-danger">Disconnected</span>}
        </div>
      </div>

      {/* 内容区 — section switching controlled by ActivityBar */}
      <div className="flex-1 overflow-y-auto p-3">
        {activeSection === 'tools' && (
          <div className="space-y-1">
            <div className="text-xs text-fg-muted uppercase tracking-wider mb-2">Desktop Control</div>
            {QUICK_TOOLS.map(tool => (
              <button
                key={tool.name}
                type="button"
                onClick={() => onExecuteTool(tool.name, tool.defaultArgs || {})}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-fg-secondary hover:bg-surface-hover transition-colors"
              >
                <tool.icon className="w-3.5 h-3.5" />
                {tool.label}
              </button>
            ))}
          </div>
        )}

        {activeSection === 'project' && (
          <div className="h-full flex flex-col">
            <ProjectPanel
              currentProject={currentProject || null}
              fileTree={fileTree}
              expandedPaths={expandedPaths}
              onTogglePath={onTogglePath || (() => {})}
              onSelectFile={onSelectFile || (() => {})}
              onOpenFolder={onOpenFolder || (() => {})}
              onOpenModal={onOpenProjectModal || (() => {})}
              onCloseProject={onCloseProject || (() => {})}
              onRefreshTree={onRefreshTree || (() => {})}
            />
          </div>
        )}

        {activeSection === 'sessions' && (
          <div className="space-y-2">
            <button
              onClick={onNewSession}
              className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs bg-accent/10 text-accent hover:bg-accent/15 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              New Session
            </button>
            <div className="text-xs text-fg-muted uppercase tracking-wider mt-2">History</div>
            {sessions.length === 0 && (
              <div className="text-xs text-fg-muted text-center py-4">No sessions yet</div>
            )}
            {sessions.map(s => (
              <div
                key={s.id}
                className={`flex items-center justify-between px-2 py-1.5 rounded text-xs cursor-pointer ${
                  s.id === currentSession ? 'bg-surface-alt text-fg' : 'text-fg-secondary hover:bg-surface-hover'
                }`}
              >
                <div className="flex items-center gap-2 flex-1 min-w-0" onClick={() => onSwitchSession?.(s.id)}>
                  <MessageSquare className="w-3.5 h-3.5 shrink-0" />
                  <span className="truncate">{s.id.replace('session_', '')}</span>
                </div>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onDeleteSession?.(s.id); }}
                  className="text-fg-muted hover:text-danger ml-1"
                  aria-label="Delete session"
                  title="Delete session"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {activeSection === 'knowledge' && (
          <div className="space-y-3">
            <div className="text-xs text-fg-muted uppercase tracking-wider">Knowledge Base</div>
            <button
              type="button"
              onClick={() => onExecuteTool('knowledge_list', {})}
              className="w-full flex items-center justify-center gap-2 py-2 rounded text-xs bg-surface-hover border border-border text-fg-secondary hover:bg-surface-alt transition-colors"
            >
              <BookOpen className="w-3.5 h-3.5" />
              View All Documents
            </button>
            <div className="text-[10px] text-fg-muted text-center">
              Browse and search your indexed knowledge base documents.
            </div>
          </div>
        )}

        {activeSection === 'settings' && (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-fg-secondary block mb-1">Role</label>
              <div className="flex gap-1">
                <select
                  value={currentRole}
                  onChange={(e) => onRoleChange(e.target.value)}
                  className="flex-1 text-xs bg-surface-input border border-border rounded px-2 py-1.5 outline-none text-fg"
                  aria-label="Select role"
                >
                  {roles.map(r => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={onOpenRoleEditor}
                  className="px-2 py-1.5 rounded text-xs bg-surface-hover border border-border text-fg-secondary hover:bg-surface-alt transition-colors"
                  title="Custom roles"
                >
                  <UserCog className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="text-[10px] text-fg-muted mt-1">
                {roles.find(r => r.id === currentRole)?.description || ''}
              </div>
            </div>

            <div>
              <label className="text-xs text-fg-secondary block mb-1.5">{t('sidebar.theme')}</label>
              <div className="flex bg-surface-hover rounded p-0.5">
                {(['dark', 'light', 'system'] as const).map((themeOpt) => (
                  <button
                    key={themeOpt}
                    type="button"
                    onClick={() => setTheme(themeOpt)}
                    className={`flex-1 flex items-center justify-center gap-1 py-1 rounded text-[10px] transition-colors ${
                      theme === themeOpt
                        ? 'bg-surface text-fg shadow-sm'
                        : 'text-fg-muted hover:text-fg-secondary'
                    }`}
                  >
                    {themeOpt === 'dark' ? <Moon className="w-3 h-3" /> : themeOpt === 'light' ? <Sun className="w-3 h-3" /> : <Laptop className="w-3 h-3" />}
                    {themeOpt === 'dark' ? t('sidebar.dark') : themeOpt === 'light' ? t('sidebar.light') : t('sidebar.system')}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-xs text-fg-secondary block mb-1.5">Language / 语言</label>
              <div className="flex bg-surface-hover rounded p-0.5">
                {(['zh', 'en'] as const).map((lng) => (
                  <button
                    key={lng}
                    type="button"
                    onClick={() => changeLanguage(lng)}
                    className={`flex-1 flex items-center justify-center gap-1 py-1 rounded text-[10px] transition-colors ${
                      i18n.language === lng
                        ? 'bg-surface text-fg shadow-sm'
                        : 'text-fg-muted hover:text-fg-secondary'
                    }`}
                  >
                    <Globe className="w-3 h-3" />
                    {lng === 'zh' ? '中文' : 'English'}
                  </button>
                ))}
              </div>
            </div>

            <button
              type="button"
              onClick={() => onExecuteTool('knowledge_list', {})}
              className="w-full flex items-center justify-center gap-2 py-2 rounded text-xs bg-surface-hover border border-border text-fg-secondary hover:bg-surface-alt transition-colors"
            >
              <BookOpen className="w-3.5 h-3.5" />
              View Knowledge Base
            </button>

            <button
              type="button"
              onClick={onOpenSettings}
              className="w-full flex items-center justify-center gap-2 py-2 rounded text-xs bg-surface-hover border border-border text-fg-secondary hover:bg-surface-alt transition-colors"
            >
              <Settings className="w-3.5 h-3.5" />
              Open Full Settings
            </button>
          </div>
        )}
      </div>

      {/* Bottom actions */}
      <div className="p-3 border-t border-border">
        <button
          type="button"
          onClick={onClear}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-danger hover:bg-surface-hover transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" />
          Clear Session
        </button>
      </div>
    </div>
  );
};