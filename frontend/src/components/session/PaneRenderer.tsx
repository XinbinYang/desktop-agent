import React, { useCallback, useRef, useState } from 'react';
import { Panel, Group, Separator } from 'react-resizable-panels';
import { X, Plus, GripVertical, Users, UserPlus, Loader2, Minus } from 'lucide-react';
import { SessionView, type SessionViewHandle } from './SessionView';
import type { PaneNode, SessionPane, SplitNode } from './PaneTypes';
import type { SessionSnapshot, SessionActions } from '../../contexts/FocusedSessionContext';
import type { AgentType, FileEdit, ModelInfo, ProjectInfo } from '../../types';
import type { Team } from '../../lib/teamStore';
import { getTeamForPane } from '../../lib/teamStore';
import { agentForRole, displayNameForAgentRole, roleForAgent, type AgentProfileMap, type RoleDisplayNameMap } from '../../lib/agentProfiles';

type DragDirection = 'top' | 'bottom' | 'left' | 'right' | 'center';
type SplitPlacement = 'before' | 'after';

interface SplitPaneOptions {
  sessionId?: string;
  placement?: SplitPlacement;
  model?: string;
  role?: string;
  agentType?: AgentType;
}

interface SessionMeta {
  title?: string;
  model_id?: string;
  role_id?: string;
  agent_type?: AgentType;
  is_primary?: boolean;
  is_running?: boolean;
}

interface DragPayload {
  leafId: string;
  paneId: string;
  sessionId: string;
  model: string;
  agentType: AgentType;
  role: string;
}

interface DropIndicator {
  direction: DragDirection;
}

interface PaneRendererProps {
  node: PaneNode;
  focusedLeafId: string | null;
  onFocus: (leafId: string) => void;
  onMinimizePane: (leafId: string) => void;
  onClosePane: (leafId: string) => void;
  onSplit: (leafId: string, direction: 'horizontal' | 'vertical', options?: SplitPaneOptions) => void;
  onMoveSession: (fromLeafId: string, toLeafId: string) => void;
  onSplitResize: (splitId: string, sizes: number[]) => void;
  teams: Team[];
  onJoinTeam: (paneId: string, teamId: string) => void;
  onCreateTeam: (name: string) => Team;
  onLeaveTeam: (paneId: string) => void;
  sessionViewRefs: React.MutableRefObject<Map<string, SessionViewHandle>>;
  currentProject: ProjectInfo | null;
  currentModel: string;
  currentAgentType: AgentType;
  currentRole: string;
  models: ModelInfo[];
  agentProfiles?: AgentProfileMap;
  roleDisplayNames?: RoleDisplayNameMap;
  sessionMetaById?: Record<string, SessionMeta>;
  onModelChange: (leafId: string, modelId: string) => void;
  onSnapshot: (snapshot: SessionSnapshot | null, actions: SessionActions) => void;
  onCommand: (command: string, args: string) => void;
  runAction: (runId: string, action: 'apply' | 'merge' | 'discard') => Promise<void>;
  openRunWorktree: (runId: string) => Promise<void>;
  handleOpenFileFromPanel: (path: string) => void;
  handleOpenFileFromPanelWithLine: (path: string, line?: number) => void;
  onRevealWorkspace?: () => void;
  onOpenPlanInWorkspace?: () => void;
  onProjectFileEdit?: (edit: FileEdit) => void;
  chrome?: 'default' | 'floating';
}

const RESIZE_TARGET_MINIMUM_SIZE = { fine: 4, coarse: 34 } as const;

function splitLayout(node: SplitNode): Record<string, number> {
  return node.children.reduce<Record<string, number>>((layout, child, index) => {
    layout[child.id] = node.sizes[index] ?? 100 / node.children.length;
    return layout;
  }, {});
}

export const PaneRenderer: React.FC<PaneRendererProps> = React.memo(function PaneRenderer({
  node,
  focusedLeafId,
  onFocus,
  onMinimizePane,
  onClosePane,
  onSplit,
  onMoveSession,
  onSplitResize,
  teams,
  onJoinTeam,
  onCreateTeam,
  onLeaveTeam,
  sessionViewRefs,
  currentProject,
  currentModel,
  currentAgentType,
  currentRole,
  models,
  agentProfiles,
  roleDisplayNames,
  sessionMetaById = {},
  onModelChange,
  onSnapshot,
  onCommand,
  runAction,
  openRunWorktree,
  handleOpenFileFromPanel,
  handleOpenFileFromPanelWithLine,
  onRevealWorkspace,
  onOpenPlanInWorkspace,
  onProjectFileEdit,
  chrome = 'default',
}) {
  if (node.type === 'leaf') {
    return (
      <LeafPane
        leafId={node.id}
        pane={node.pane}
        isFocused={node.id === focusedLeafId}
        team={getTeamForPane(teams, node.pane.id)}
        onFocus={() => onFocus(node.id)}
        onMinimize={() => onMinimizePane(node.id)}
        onClose={() => onClosePane(node.id)}
        onSplit={onSplit}
        onMoveSession={onMoveSession}
        teams={teams}
        onJoinTeam={onJoinTeam}
        onCreateTeam={onCreateTeam}
        onLeaveTeam={onLeaveTeam}
        sessionViewRefs={sessionViewRefs}
        currentProject={currentProject}
        currentModel={currentModel}
        currentAgentType={currentAgentType}
        currentRole={currentRole}
        models={models}
        agentProfiles={agentProfiles}
        roleDisplayNames={roleDisplayNames}
        sessionMetaById={sessionMetaById}
        onModelChange={onModelChange}
        onSnapshot={node.id === focusedLeafId ? onSnapshot : () => {}}
        onCommand={onCommand}
        runAction={runAction}
        openRunWorktree={openRunWorktree}
        handleOpenFileFromPanel={handleOpenFileFromPanel}
        handleOpenFileFromPanelWithLine={handleOpenFileFromPanelWithLine}
        onRevealWorkspace={onRevealWorkspace}
        onOpenPlanInWorkspace={onOpenPlanInWorkspace}
        onProjectFileEdit={onProjectFileEdit}
        chrome={chrome}
      />
    );
  }

  return (
    <Group
      id={node.id}
      orientation={node.direction}
      defaultLayout={splitLayout(node)}
      onLayoutChanged={(layout) => {
        onSplitResize(node.id, node.children.map((child, index) => layout[child.id] ?? node.sizes[index] ?? 100 / node.children.length));
      }}
      className="flex-1 min-h-0"
      resizeTargetMinimumSize={RESIZE_TARGET_MINIMUM_SIZE}
    >
      {node.children.map((child, index) => (
        <React.Fragment key={child.id}>
          {index > 0 && (
            <Separator
              className={
                node.direction === 'horizontal'
                  ? 'w-px bg-border hover:bg-accent/50 active:bg-accent/70 transition-colors cursor-col-resize'
                  : 'h-px bg-border hover:bg-accent/50 active:bg-accent/70 transition-colors cursor-row-resize'
              }
            />
          )}
          <Panel
            id={child.id}
            defaultSize={`${node.sizes[index] ?? 100 / node.children.length}%`}
            minSize={chrome === 'floating' && node.direction === 'horizontal' ? '360px' : '220px'}
          >
            <PaneRenderer
              node={child}
              focusedLeafId={focusedLeafId}
              onFocus={onFocus}
              onMinimizePane={onMinimizePane}
              onClosePane={onClosePane}
              onSplit={onSplit}
              onMoveSession={onMoveSession}
              onSplitResize={onSplitResize}
              teams={teams}
              onJoinTeam={onJoinTeam}
              onCreateTeam={onCreateTeam}
              onLeaveTeam={onLeaveTeam}
              sessionViewRefs={sessionViewRefs}
              currentProject={currentProject}
              currentModel={currentModel}
              currentAgentType={currentAgentType}
              currentRole={currentRole}
              models={models}
              agentProfiles={agentProfiles}
              roleDisplayNames={roleDisplayNames}
              sessionMetaById={sessionMetaById}
              onModelChange={onModelChange}
              onSnapshot={onSnapshot}
              onCommand={onCommand}
              runAction={runAction}
              openRunWorktree={openRunWorktree}
              handleOpenFileFromPanel={handleOpenFileFromPanel}
              handleOpenFileFromPanelWithLine={handleOpenFileFromPanelWithLine}
              onRevealWorkspace={onRevealWorkspace}
              onOpenPlanInWorkspace={onOpenPlanInWorkspace}
              onProjectFileEdit={onProjectFileEdit}
              chrome={chrome}
            />
          </Panel>
        </React.Fragment>
      ))}
    </Group>
  );
});

interface LeafPaneProps {
  leafId: string;
  pane: SessionPane;
  isFocused: boolean;
  team?: Team;
  onFocus: () => void;
  onMinimize: () => void;
  onClose: () => void;
  onSplit: (leafId: string, direction: 'horizontal' | 'vertical', options?: SplitPaneOptions) => void;
  onMoveSession: (fromLeafId: string, toLeafId: string) => void;
  teams: Team[];
  onJoinTeam: (paneId: string, teamId: string) => void;
  onCreateTeam: (name: string) => Team;
  onLeaveTeam: (paneId: string) => void;
  sessionViewRefs: React.MutableRefObject<Map<string, SessionViewHandle>>;
  currentProject: ProjectInfo | null;
  currentModel: string;
  currentAgentType: AgentType;
  currentRole: string;
  models: ModelInfo[];
  agentProfiles?: AgentProfileMap;
  roleDisplayNames?: RoleDisplayNameMap;
  sessionMetaById: Record<string, SessionMeta>;
  onModelChange: (leafId: string, modelId: string) => void;
  onSnapshot: (snapshot: SessionSnapshot | null, actions: SessionActions) => void;
  onCommand: (command: string, args: string) => void;
  runAction: (runId: string, action: 'apply' | 'merge' | 'discard') => Promise<void>;
  openRunWorktree: (runId: string) => Promise<void>;
  handleOpenFileFromPanel: (path: string) => void;
  handleOpenFileFromPanelWithLine: (path: string, line?: number) => void;
  onRevealWorkspace?: () => void;
  onOpenPlanInWorkspace?: () => void;
  onProjectFileEdit?: (edit: FileEdit) => void;
  chrome?: 'default' | 'floating';
}

const LeafPane: React.FC<LeafPaneProps> = React.memo(function LeafPane({
  leafId,
  pane,
  isFocused,
  team,
  onFocus,
  onMinimize,
  onClose,
  onSplit,
  onMoveSession,
  teams,
  onJoinTeam,
  onCreateTeam,
  onLeaveTeam,
  sessionViewRefs,
  currentProject,
  currentModel,
  currentAgentType,
  currentRole,
  models,
  agentProfiles,
  roleDisplayNames,
  sessionMetaById,
  onModelChange,
  onSnapshot,
  onCommand,
  runAction,
  openRunWorktree,
  handleOpenFileFromPanel,
  handleOpenFileFromPanelWithLine,
  onRevealWorkspace,
  onOpenPlanInWorkspace,
  onProjectFileEdit,
  chrome = 'default',
}) {
  const [indicator, setIndicator] = useState<DropIndicator | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);
  const [newTeamInput, setNewTeamInput] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  const handleTabDragStart = useCallback((event: React.DragEvent) => {
    const payload: DragPayload = {
      leafId,
      paneId: pane.id,
      sessionId: pane.sessionId,
      model: pane.model || currentModel,
      agentType: pane.agentType || agentForRole(pane.role),
      role: pane.role || currentRole,
    };
    event.dataTransfer.setData('application/x-desktop-agent-pane', JSON.stringify(payload));
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setDragImage(new Image(), 0, 0);
    (window as any).__desktop_agent_drag_payload = payload;
  }, [leafId, pane.id, pane.sessionId, pane.model, pane.agentType, pane.role, currentModel, currentRole]);

  const handleTabDragEnd = useCallback(() => {
    setIndicator(null);
    setDragOver(false);
    delete (window as any).__desktop_agent_drag_payload;
  }, []);

  const calcDirection = useCallback((event: React.DragEvent): DragDirection => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return 'center';
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const pctX = x / rect.width;
    const pctY = y / rect.height;

    if (pctX > 0.35 && pctX < 0.65 && pctY > 0.35 && pctY < 0.65) return 'center';

    const distances: Array<[DragDirection, number]> = [
      ['top', pctY],
      ['bottom', 1 - pctY],
      ['left', pctX],
      ['right', 1 - pctX],
    ];
    distances.sort((a, b) => a[1] - b[1]);
    return distances[0][0];
  }, []);

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    const payload = (window as any).__desktop_agent_drag_payload as DragPayload | undefined;
    if (!payload || payload.leafId === leafId) {
      event.dataTransfer.dropEffect = 'none';
      return;
    }
    event.dataTransfer.dropEffect = 'move';
    setDragOver(true);
    setIndicator({ direction: calcDirection(event) });
  }, [leafId, calcDirection]);

  const handleDragLeave = useCallback((event: React.DragEvent) => {
    if (!containerRef.current?.contains(event.relatedTarget as Node)) {
      setDragOver(false);
      setIndicator(null);
    }
  }, []);

  const handleContextMenu = useCallback((event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    onFocus();
    setCtxMenu({ x: event.clientX, y: event.clientY });
  }, [onFocus]);

  const closeCtxMenu = useCallback(() => {
    setCtxMenu(null);
    setNewTeamInput('');
  }, []);

  const handleJoinTeam = useCallback((teamId: string) => {
    onJoinTeam(pane.id, teamId);
    closeCtxMenu();
  }, [pane.id, onJoinTeam, closeCtxMenu]);

  const handleCreateAndJoin = useCallback(() => {
    const name = newTeamInput.trim();
    if (!name) return;
    const team = onCreateTeam(name);
    onJoinTeam(pane.id, team.id);
    closeCtxMenu();
  }, [newTeamInput, pane.id, onCreateTeam, onJoinTeam, closeCtxMenu]);

  const handleLeave = useCallback(() => {
    onLeaveTeam(pane.id);
    closeCtxMenu();
  }, [pane.id, onLeaveTeam, closeCtxMenu]);

  const handleDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setDragOver(false);
    setIndicator(null);

    const payload = (window as any).__desktop_agent_drag_payload as DragPayload | undefined;
    if (!payload || payload.leafId === leafId) return;

    const direction = calcDirection(event);
    if (direction === 'center') {
      onMoveSession(payload.leafId, leafId);
      return;
    }

    onSplit(leafId, direction === 'left' || direction === 'right' ? 'horizontal' : 'vertical', {
      sessionId: payload.sessionId,
      placement: direction === 'left' || direction === 'top' ? 'before' : 'after',
      model: payload.model,
      agentType: payload.agentType,
      role: payload.role,
    });
  }, [leafId, calcDirection, onSplit, onMoveSession]);

  const indicatorStyle = (direction: DragDirection): React.CSSProperties | undefined => {
    if (!indicator || indicator.direction !== direction) return undefined;
    const background = 'color-mix(in srgb, var(--accent) 18%, transparent)';
    const border = '2px solid color-mix(in srgb, var(--accent) 62%, transparent)';
    const base: React.CSSProperties = { position: 'absolute', zIndex: 20, pointerEvents: 'none', background, border };

    switch (direction) {
      case 'top': return { ...base, top: 0, left: 0, right: 0, height: '35%', borderBottom: 'none', borderTop: 'none' };
      case 'bottom': return { ...base, bottom: 0, left: 0, right: 0, height: '35%', borderTop: 'none', borderBottom: 'none' };
      case 'left': return { ...base, left: 0, top: 0, bottom: 0, width: '30%', borderRight: 'none', borderLeft: 'none' };
      case 'right': return { ...base, right: 0, top: 0, bottom: 0, width: '30%', borderLeft: 'none', borderRight: 'none' };
      default: return undefined;
    }
  };

  const borderColor = team?.color;
  const meta = sessionMetaById[pane.sessionId];
  const agentType = pane.agentType || meta?.agent_type || agentForRole(pane.role);
  const roleId = pane.role || meta?.role_id || roleForAgent(agentType);
  const assistantDisplayName = displayNameForAgentRole(agentType, roleId, agentProfiles, roleDisplayNames);
  const agentLabel = assistantDisplayName;
  const paneTitle = agentType === 'personal' && (pane.isPrimary || meta?.is_primary || pane.sessionId === 'session_personal_main')
    ? 'Main'
    : (meta?.title || pane.title || pane.sessionId.replace(/^session_(coding_)?/, '#'));
  const modelLabel = pane.model || meta?.model_id || currentModel;
  const modelOptions = modelLabel && !models.some((model) => model.id === modelLabel)
    ? [{ id: modelLabel, name: modelLabel, provider: '', vision: false, context: 0 }, ...models]
    : models;
  const floatingChrome = chrome === 'floating';

  return (
    <div
      ref={containerRef}
      className={`h-full flex flex-col relative ${
        floatingChrome
          ? `${dragOver ? 'bg-accent/5' : 'bg-transparent'}`
          : `border rounded ${
              !team && (isFocused ? 'border-accent/40' : dragOver ? 'border-accent/70 bg-accent/5' : 'border-border')
            }`
      } transition-colors`}
      style={!floatingChrome && team ? { borderColor, borderWidth: 2 } : undefined}
      onClick={onFocus}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onContextMenu={handleContextMenu}
    >
      {indicator && indicatorStyle(indicator.direction) && (
        <div style={indicatorStyle(indicator.direction)!} />
      )}
      {indicator?.direction === 'center' && (
        <div className="absolute inset-[15%] bg-accent/10 border-2 border-accent border-dashed rounded z-20 pointer-events-none flex items-center justify-center">
          <span className="text-xs text-accent font-medium">Swap session</span>
        </div>
      )}

      {team && (
        <div className="h-4 flex items-center shrink-0 px-2 rounded-t" style={{ backgroundColor: `${team.color}30` }}>
          <Users className="w-2.5 h-2.5 mr-1 shrink-0" style={{ color: team.color }} />
          <span className="text-[9px] font-medium truncate" style={{ color: team.color }}>{team.name}</span>
        </div>
      )}

      <div
        className={`h-7 flex items-center shrink-0 border-b px-1 gap-0.5 ${
          floatingChrome ? '' : team ? '' : 'rounded-t'
        } ${
          floatingChrome
            ? isFocused ? 'bg-surface-alt/75 border-accent/20' : 'bg-surface/70 border-border-subtle'
            : isFocused ? 'bg-surface-alt border-accent/20' : 'bg-surface border-border'
        } ${dragOver ? 'bg-accent/5' : ''}`}
        onContextMenu={handleContextMenu}
      >
        <div
          className="flex min-w-0 flex-1 items-center gap-0.5 self-stretch cursor-grab active:cursor-grabbing"
          draggable
          onDragStart={handleTabDragStart}
          onDragEnd={handleTabDragEnd}
          onClick={onFocus}
          title="Drag to split or swap pane"
          aria-label="Drag pane"
        >
          <GripVertical className="w-3 h-3 text-fg-muted shrink-0 pointer-events-none" />
          <span className="text-[10px] font-semibold text-fg truncate px-1 select-none pointer-events-none">
            {agentLabel}
          </span>
          <span className="text-[10px] text-fg-secondary truncate px-0.5 select-none pointer-events-none">
            {paneTitle}
          </span>
          <span className="w-3 h-3 shrink-0 pointer-events-none" aria-hidden={!meta?.is_running}>
            {meta?.is_running && (
              <Loader2
                className="w-3 h-3 animate-spin text-success"
                aria-label="Session running"
              />
            )}
          </span>
        </div>
        <select
          value={modelLabel}
          aria-label="Pane model"
          title={`Model for ${agentLabel} ${paneTitle}`}
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => {
            event.stopPropagation();
            onFocus();
            onModelChange(leafId, event.target.value);
          }}
          className="h-5 max-w-[42%] min-w-[88px] shrink text-[9px] text-fg-muted bg-surface border border-transparent hover:border-border focus:border-accent/50 rounded px-1 outline-none cursor-pointer app-no-drag"
        >
          {!modelLabel && <option value="">No model</option>}
          {modelOptions.map((model) => (
            <option key={model.id} value={model.id}>
              {model.name || model.id}
            </option>
          ))}
        </select>
        <button
          type="button"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => { event.stopPropagation(); onMinimize(); }}
          className="p-0.5 text-fg-muted hover:text-fg hover:bg-surface-hover rounded shrink-0"
          title="Minimize pane"
          aria-label="Minimize pane"
        >
          <Minus className="w-3 h-3" />
        </button>
        <button
          type="button"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => { event.stopPropagation(); onFocus(); onSplit(leafId, 'horizontal', { placement: 'after', agentType: 'coding' }); }}
          className="p-0.5 text-fg-muted hover:text-fg hover:bg-surface-hover rounded shrink-0"
          title="New Coding Session in Split Pane"
          aria-label="New Coding Session in Split Pane"
        >
          <Plus className="w-3 h-3" />
        </button>
        <button
          type="button"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => { event.stopPropagation(); onClose(); }}
          className="p-0.5 text-fg-muted hover:text-fg hover:bg-surface-hover rounded shrink-0"
          title="Close pane"
          aria-label="Close pane"
        >
          <X className="w-3 h-3" />
        </button>
      </div>

      {ctxMenu && (
        <>
          <div className="fixed inset-0 z-40" onClick={closeCtxMenu} onContextMenu={(event) => { event.preventDefault(); closeCtxMenu(); }} />
          <div
            className="fixed z-50 bg-surface border border-border rounded shadow-lg py-1 min-w-[160px]"
            style={{ left: Math.min(ctxMenu.x, window.innerWidth - 170), top: Math.min(ctxMenu.y, window.innerHeight - 200) }}
          >
            <div className="px-2 py-0.5 text-[10px] text-fg-muted font-medium">Join Team</div>
            {teams.map((team) => (
              <button
                key={team.id}
                type="button"
                className="flex items-center gap-2 w-full px-2 py-1 text-[11px] hover:bg-surface-hover text-fg-secondary"
                onClick={() => handleJoinTeam(team.id)}
              >
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: team.color }} />
                <span className="truncate">{team.name}</span>
                <span className="ml-auto text-fg-muted text-[10px]">{team.memberPaneIds.length}</span>
              </button>
            ))}
            {teams.length === 0 && (
              <div className="px-2 py-1 text-[11px] text-fg-muted">No teams</div>
            )}
            <div className="border-t border-border my-0.5" />
            <div className="flex items-center gap-1 px-2 py-1">
              <input
                value={newTeamInput}
                onChange={(event) => setNewTeamInput(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') handleCreateAndJoin(); }}
                placeholder="New team name..."
                className="flex-1 text-[11px] bg-surface-alt border border-border rounded px-1.5 py-0.5 outline-none text-fg"
                onClick={(event) => event.stopPropagation()}
              />
              <button
                type="button"
                onClick={handleCreateAndJoin}
                disabled={!newTeamInput.trim()}
                className="p-0.5 text-accent hover:bg-accent/10 rounded disabled:opacity-30"
                aria-label="Create and join team"
              >
                <UserPlus className="w-3 h-3" />
              </button>
            </div>
            {team && (
              <>
                <div className="border-t border-border my-0.5" />
                <button
                  type="button"
                  className="flex items-center gap-2 w-full px-2 py-1 text-[11px] hover:bg-surface-hover text-danger"
                  onClick={handleLeave}
                >
                  Remove from "{team.name}"
                </button>
              </>
            )}
          </div>
        </>
      )}

      <div className="flex-1 min-h-0">
        <SessionView
          ref={(ref) => {
            if (ref) sessionViewRefs.current.set(pane.sessionId, ref);
            else sessionViewRefs.current.delete(pane.sessionId);
          }}
          sessionId={pane.sessionId}
          model={modelLabel}
          agentType={agentType}
          role={roleId}
          assistantDisplayName={assistantDisplayName}
          teamId={pane.teamId}
          teamName={team?.name}
          isFocused={isFocused}
          onFocus={onFocus}
          currentProject={currentProject}
          onSnapshot={onSnapshot}
          onCommand={onCommand}
          runAction={runAction}
          openRunWorktree={openRunWorktree}
          handleOpenFileFromPanel={handleOpenFileFromPanel}
          handleOpenFileFromPanelWithLine={handleOpenFileFromPanelWithLine}
          onRevealWorkspace={onRevealWorkspace}
          onOpenPlanInWorkspace={onOpenPlanInWorkspace}
          onProjectFileEdit={onProjectFileEdit}
        />
      </div>
    </div>
  );
});
