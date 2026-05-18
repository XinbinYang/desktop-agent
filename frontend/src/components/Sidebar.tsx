import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Trash2, Zap,
  Globe, Plus, MessageSquare, X, Archive, RotateCcw,
  UserCog, Settings, BookOpen, Sun, Moon, Laptop,
  Brain, Activity, Moon as MoonIcon, Sparkles, FolderOpen
} from 'lucide-react';
import { ProjectInfo, FileNode, SidebarSection, type AgentType } from '../types';
import { ProjectPanel } from './ProjectPanel';
import { SkillsPanel } from './SkillsPanel';
import { useTheme } from '../hooks/useTheme';
import { AGENT_LABEL } from '../lib/agentProfiles';

interface SidebarProps {
  activeSection: SidebarSection;
  activeAgent?: AgentType;
  onSectionChange: (section: SidebarSection) => void;
  onAgentChange?: (agent: AgentType) => void;
  agentModel?: string;
  onOpenPersonalWorkspace?: () => void;
  onOpenSettings: () => void;
  onClear: () => void;
  onExecuteTool: (name: string, args: any) => void;
  isConnected: boolean;
  sessions?: {id: string; title?: string; project_path?: string; model_id: string; role_id?: string; agent_type?: AgentType; message_count: number; updated_at?: number; is_primary?: boolean}[];
  currentSession?: string;
  onNewSession?: () => void;
  onCompactSession?: () => void;
  onRewindSession?: () => void;
  onSwitchSession?: (id: string) => void;
  onDeleteSession?: (id: string) => void;
  currentProjectPath?: string | null;
  // 项目相关
  currentProject?: ProjectInfo | null;
  fileTree?: FileNode[];
  expandedPaths?: Set<string>;
  loadingPaths?: Set<string>;
  onTogglePath?: (path: string) => void;
  onSelectFile?: (path: string, type: 'file' | 'dir') => void;
  onOpenFolder?: () => void;
  onOpenProjectModal?: () => void;
  onCloseProject?: () => void;
  onRefreshTree?: () => void | Promise<void>;
  isRefreshingProject?: boolean;
}

type SessionItem = {id: string; title?: string; project_path?: string; model_id: string; role_id?: string; agent_type?: AgentType; message_count: number; updated_at?: number; is_primary?: boolean};

function formatSessionLabel(s: SessionItem): string {
  if (s.title) return s.title.length > 40 ? s.title.slice(0, 40) + '…' : s.title;
  // Fallback: parse timestamp from session ID
  const ts = parseInt(s.id.replace('session_', ''), 10);
  if (ts > 0) {
    return new Date(ts).toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  }
  return s.id.replace('session_', '');
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeSection,
  activeAgent = 'personal',
  onSectionChange,
  agentModel = '',
  onOpenPersonalWorkspace,
  onOpenSettings,
  onClear,
  onExecuteTool,
  isConnected,
  sessions = [],
  currentSession,
  onNewSession,
  onCompactSession,
  onRewindSession,
  onSwitchSession,
  onDeleteSession,
  currentProjectPath,
  // 项目
  currentProject,
  fileTree = [],
  expandedPaths = new Set(),
  loadingPaths = new Set(),
  onTogglePath,
  onSelectFile,
  onOpenFolder,
  onOpenProjectModal,
  onCloseProject,
  onRefreshTree,
  isRefreshingProject = false,
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
        {activeSection === 'personal' && (
          <div className="space-y-4">
            <div className="text-xs font-medium text-fg-muted">Personal Agent</div>

            {/* Persona section */}
            <div>
              <div className="text-[10px] text-fg-muted uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <UserCog className="w-3 h-3" /> Persona
              </div>
              <button
                type="button"
                onClick={onOpenPersonalWorkspace}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-fg-secondary hover:bg-surface-hover transition-colors"
              >
                <UserCog className="w-3.5 h-3.5" />
                Edit SOUL / INNER / IDENTITY / USER
              </button>
            </div>

            {/* Memory section */}
            <div>
              <div className="text-[10px] text-fg-muted uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <Brain className="w-3 h-3" /> Memory
              </div>
              <button
                type="button"
                onClick={() => onExecuteTool?.('memory_list', {})}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-fg-secondary hover:bg-surface-hover transition-colors"
              >
                <BookOpen className="w-3.5 h-3.5" />
                Search Memory
              </button>
            </div>

            {/* Cognitive system status */}
            <div>
              <div className="text-[10px] text-fg-muted uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <Activity className="w-3 h-3" /> Cognitive System
              </div>
              <div className="space-y-0.5 text-[10px] text-fg-muted">
                <div className="flex items-center gap-1.5 px-2 py-0.5">
                  <Activity className="w-2.5 h-2.5 text-green-400" />
                  HEARTBEAT: active
                </div>
                <div className="flex items-center gap-1.5 px-2 py-0.5">
                  <MoonIcon className="w-2.5 h-2.5 text-fg-muted" />
                  DREAM: on trigger
                </div>
                <div className="flex items-center gap-1.5 px-2 py-0.5">
                  <Sparkles className="w-2.5 h-2.5 text-fg-muted" />
                  EVOLUTION: on trigger
                </div>
              </div>
            </div>

            {/* Open full panel */}
            <div className="text-[10px] text-fg-muted text-center pt-2 border-t border-border">
              Full workspace panel available in the right panel (Ctrl+\)
            </div>
          </div>
        )}

        {activeSection === 'coding' && (
          <div className="space-y-3">
            <div className="text-xs font-medium text-fg-muted">Coding Agent</div>
            {currentProject ? (
              <div className="h-full flex flex-col">
                <ProjectPanel
                  currentProject={currentProject}
                  fileTree={fileTree}
                  expandedPaths={expandedPaths}
                  loadingPaths={loadingPaths}
                  onTogglePath={onTogglePath || (() => {})}
                  onSelectFile={onSelectFile || (() => {})}
                  onOpenFolder={onOpenFolder || (() => {})}
                  onOpenModal={onOpenProjectModal || (() => {})}
                  onCloseProject={onCloseProject || (() => {})}
                  onRefreshTree={onRefreshTree || (() => {})}
                  isRefreshing={isRefreshingProject}
                />
              </div>
            ) : (
              <div className="text-xs text-fg-muted text-center py-4">
                <FolderOpen className="w-5 h-5 mx-auto mb-2 opacity-30" />
                <p>No project open.</p>
                <button
                  type="button"
                  onClick={onOpenFolder}
                  className="mt-2 text-accent hover:underline text-[11px]"
                >
                  Open a folder
                </button>
              </div>
            )}
          </div>
        )}

        {activeSection === 'skills' && (
          <SkillsPanel activeAgent={activeAgent} />
        )}

        {activeSection === 'project' && (
          <div className="h-full flex flex-col">
            <ProjectPanel
              currentProject={currentProject || null}
              fileTree={fileTree}
              expandedPaths={expandedPaths}
              loadingPaths={loadingPaths}
              onTogglePath={onTogglePath || (() => {})}
              onSelectFile={onSelectFile || (() => {})}
              onOpenFolder={onOpenFolder || (() => {})}
              onOpenModal={onOpenProjectModal || (() => {})}
              onCloseProject={onCloseProject || (() => {})}
              onRefreshTree={onRefreshTree || (() => {})}
              isRefreshing={isRefreshingProject}
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
              /new
            </button>
            <div className="grid grid-cols-2 gap-1.5">
              <button
                type="button"
                onClick={onCompactSession}
                className="flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-xs bg-surface-alt text-fg-secondary hover:bg-surface-hover hover:text-fg transition-colors"
                title="Compact current session context"
              >
                <Archive className="w-3.5 h-3.5" />
                /compact
              </button>
              <button
                type="button"
                onClick={onRewindSession}
                className="flex items-center justify-center gap-1.5 px-2 py-1.5 rounded text-xs bg-surface-alt text-fg-secondary hover:bg-surface-hover hover:text-fg transition-colors"
                title="Rewind to a previous checkpoint"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                /rewind
              </button>
            </div>
            <div className="flex items-center justify-between mt-2">
              <span className="text-xs font-medium text-fg-muted">History</span>
              {currentProjectPath && (
                <span className="text-[10px] text-accent/80 bg-accent/10 px-1.5 py-0.5 rounded" title={`Filtered: ${currentProjectPath}`}>
                  Project
                </span>
              )}
            </div>
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
                  <span className="truncate">{s.is_primary ? 'Personal Agent · Main' : formatSessionLabel(s)}</span>
                  <span className={`text-[9px] px-1 py-0.5 rounded shrink-0 ${
                    (s.agent_type || 'personal') === 'coding'
                      ? 'bg-success/10 text-success'
                      : 'bg-accent/10 text-accent'
                  }`}>
                    {(s.agent_type || 'personal') === 'coding' ? 'Coding' : 'Personal'}
                  </span>
                </div>
                {!s.is_primary && (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onDeleteSession?.(s.id); }}
                    className="text-fg-muted hover:text-danger ml-1"
                    aria-label="Delete session"
                    title="Delete session"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {activeSection === 'settings' && (
          <div className="space-y-4">
            <div>
              <label className="text-xs text-fg-secondary block mb-1.5">Active Agent</label>
              <div className="rounded border border-border bg-surface-alt px-2 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium text-fg">{AGENT_LABEL[activeAgent]}</span>
                  <span className="text-[10px] text-fg-muted">ready</span>
                </div>
                {agentModel && (
                  <div className="mt-1 truncate text-[10px] text-fg-muted" title={agentModel}>
                    Model: {agentModel}
                  </div>
                )}
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
