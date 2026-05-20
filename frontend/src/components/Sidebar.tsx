import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Trash2, Zap,
  Globe,
  UserCog, Settings, BookOpen, Sun, Moon, Laptop,
  Brain, Activity, Moon as MoonIcon, Sparkles
} from 'lucide-react';
import { ProjectInfo, FileNode, SidebarSection, type AgentType, type SessionHistoryItem, type SessionHistoryResponse } from '../types';
import type { FileTreeAction } from './FileTree';
import { SkillsPanel } from './SkillsPanel';
import { useTheme } from '../hooks/useTheme';
import { AGENT_LABEL } from '../lib/agentProfiles';
import { type ProjectHistoryAction } from './SessionHistoryPanel';
import { WorkspacePanel } from './WorkspacePanel';
import type { PersonalWorkspaceTab } from './PersonalWorkspace/PersonalWorkspacePanel';

interface SidebarProps {
  activeSection: SidebarSection;
  activeAgent?: AgentType;
  onSectionChange: (section: SidebarSection) => void;
  onAgentChange?: (agent: AgentType) => void;
  agentModel?: string;
  onOpenPersonalWorkspace?: (tab?: PersonalWorkspaceTab) => void;
  onOpenSettings: () => void;
  onClear: () => void;
  onExecuteTool: (name: string, args: any) => void;
  isConnected: boolean;
  skillsRefreshToken?: number;
  highlightedSkillDraftId?: string | null;
  sessionHistory?: SessionHistoryResponse | null;
  sessions?: SessionHistoryItem[];
  currentSession?: string;
  onNewSession?: () => void;
  onCompactSession?: () => void;
  onRewindSession?: () => void;
  onSwitchSession?: (id: string, projectPath?: string | null) => void;
  onArchiveSession?: (id: string) => void;
  onDeleteSession?: (id: string) => void;
  onOpenProject?: (path: string) => void;
  onProjectAction?: (action: ProjectHistoryAction, project: SessionHistoryResponse['projects'][number]) => void;
  onNewProjectSession?: (project: SessionHistoryResponse['projects'][number]) => void;
  currentProjectPath?: string | null;
  // 项目相关
  currentProject?: ProjectInfo | null;
  fileTree?: FileNode[];
  expandedPaths?: Set<string>;
  loadingPaths?: Set<string>;
  onTogglePath?: (path: string) => void;
  onSelectFile?: (path: string, type: 'file' | 'dir') => void;
  onFileAction?: (action: FileTreeAction, node: FileNode) => void;
  onOpenFolder?: () => void;
  onOpenProjectModal?: () => void;
  onCloseProject?: () => void;
  onRefreshTree?: () => void | Promise<void>;
  isRefreshingProject?: boolean;
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
  skillsRefreshToken = 0,
  highlightedSkillDraftId = null,
  sessionHistory = null,
  sessions = [],
  currentSession,
  onNewSession,
  onCompactSession,
  onRewindSession,
  onSwitchSession,
  onArchiveSession,
  onDeleteSession,
  onOpenProject,
  onProjectAction,
  onNewProjectSession,
  currentProjectPath,
  // 项目
  currentProject,
  fileTree = [],
  expandedPaths = new Set(),
  loadingPaths = new Set(),
  onTogglePath,
  onSelectFile,
  onFileAction,
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
    <div className="h-full w-full bg-surface border-r border-border flex flex-col">
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
                onClick={() => onOpenPersonalWorkspace?.('persona')}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-fg-secondary hover:bg-surface-hover transition-colors"
              >
                <UserCog className="w-3.5 h-3.5" />
                查看/修正身份与偏好
              </button>
            </div>

            {/* Memory section */}
            <div>
              <div className="text-[10px] text-fg-muted uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <Brain className="w-3 h-3" /> Memory
              </div>
              <button
                type="button"
                onClick={() => onOpenPersonalWorkspace?.('memory')}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs text-fg-secondary hover:bg-surface-hover transition-colors"
              >
                <BookOpen className="w-3.5 h-3.5" />
                查看 Agent 记忆
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
                  自动维护：自动运行
                </div>
                <div className="flex items-center gap-1.5 px-2 py-0.5">
                  <MoonIcon className="w-2.5 h-2.5 text-fg-muted" />
                  记忆整理：自动触发
                </div>
                <div className="flex items-center gap-1.5 px-2 py-0.5">
                  <Sparkles className="w-2.5 h-2.5 text-fg-muted" />
                  能力进化：自动判断
                </div>
              </div>
            </div>

            {/* Open full panel */}
            <div className="text-[10px] text-fg-muted text-center pt-2 border-t border-border">
              Full workspace panel available in the right panel (Ctrl+\)
            </div>
          </div>
        )}

        {(activeSection === 'workspace' || activeSection === 'coding') && (
          <div className="h-full">
            <WorkspacePanel
              sessionHistory={sessionHistory}
              sessions={sessions}
              currentSession={currentSession}
              currentProjectPath={currentProjectPath}
              onNewSession={onNewSession}
              onCompactSession={onCompactSession}
              onRewindSession={onRewindSession}
              onSwitchSession={onSwitchSession}
              onArchiveSession={onArchiveSession}
              onDeleteSession={onDeleteSession}
              onOpenProject={onOpenProject}
              onOpenProjectModal={onOpenProjectModal}
              onProjectAction={onProjectAction}
              onNewProjectSession={onNewProjectSession}
              currentProject={currentProject}
              fileTree={fileTree}
              expandedPaths={expandedPaths}
              loadingPaths={loadingPaths}
              onTogglePath={onTogglePath}
              onSelectFile={onSelectFile}
              onFileAction={onFileAction}
              onOpenFolder={onOpenFolder}
              onCloseProject={onCloseProject}
              onRefreshTree={onRefreshTree}
              isRefreshingProject={isRefreshingProject}
            />
          </div>
        )}

        {activeSection === 'skills' && (
          <SkillsPanel
            activeAgent={activeAgent}
            refreshToken={skillsRefreshToken}
            highlightedDraftId={highlightedSkillDraftId}
          />
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
