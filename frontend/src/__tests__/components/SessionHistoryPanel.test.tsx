import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { SessionHistoryPanel } from '../../components/SessionHistoryPanel';
import type { SessionHistoryResponse } from '../../types';

function historyFixture(): SessionHistoryResponse {
  const now = Date.now() / 1000;
  return {
    current_project_path: 'C:/repo',
    projects: [
      {
        path: 'C:/repo',
        name: 'repo',
        last_opened: '2026-05-18T00:00:00Z',
        is_current: true,
        has_running: true,
        is_pinned: false,
        is_archived: false,
        archived_sessions_count: 0,
        source: 'recent',
        sessions: [
          {
            id: 'session_running',
            title: 'Implement agent history',
            project_path: 'C:/repo',
            model_id: 'gpt-4o',
            role_id: 'code-expert',
            agent_type: 'coding',
            message_count: 4,
            updated_at: now - 60,
            is_primary: false,
            is_running: true,
            active_connections: 1,
            activity_state: 'running',
          },
          {
            id: 'session_idle',
            title: 'Idle task',
            project_path: 'C:/repo',
            model_id: 'gpt-4o',
            role_id: 'code-expert',
            agent_type: 'coding',
            message_count: 2,
            updated_at: now - 3600,
            is_primary: false,
            is_running: false,
            active_connections: 0,
            activity_state: 'idle',
          },
        ],
      },
    ],
    standalone_sessions: [
      {
        id: 'session_personal_main',
        title: '',
        project_path: null,
        model_id: 'gpt-4o',
        role_id: 'desktop-agent',
        agent_type: 'personal',
        message_count: 1,
        updated_at: now - 7200,
        is_primary: true,
        is_running: false,
        active_connections: 0,
        activity_state: 'idle',
      },
    ],
  };
}

describe('SessionHistoryPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-05-18T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders project sessions with running state and session actions', () => {
    const onSwitchSession = vi.fn();
    const onArchiveSession = vi.fn();
    const onDeleteSession = vi.fn();
    const onOpenProject = vi.fn();
    const onOpenProjectModal = vi.fn();
    const onNewProjectSession = vi.fn();

    render(
      <SessionHistoryPanel
        history={historyFixture()}
        currentSession="session_running"
        currentProjectPath="C:/repo"
        onSwitchSession={onSwitchSession}
        onArchiveSession={onArchiveSession}
        onDeleteSession={onDeleteSession}
        onOpenProject={onOpenProject}
        onOpenProjectModal={onOpenProjectModal}
        onNewProjectSession={onNewProjectSession}
      />,
    );

    fireEvent.click(screen.getByText('New project'));
    expect(onOpenProjectModal).toHaveBeenCalled();

    expect(screen.getByText('repo')).toBeInTheDocument();
    expect(screen.getByText('Implement agent history')).toBeInTheDocument();
    expect(screen.getAllByLabelText('Session running')).toHaveLength(1);
    expect(screen.getByText('1 小时')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Open project repo'));
    expect(onOpenProject).toHaveBeenCalledWith('C:/repo');

    fireEvent.click(screen.getByLabelText('Start new session in repo'));
    expect(onNewProjectSession).toHaveBeenCalledWith(expect.objectContaining({ path: 'C:/repo' }));

    fireEvent.click(screen.getByLabelText('Open session Idle task'));
    expect(onSwitchSession).toHaveBeenCalledWith('session_idle', 'C:/repo');

    fireEvent.click(screen.getByLabelText('Session actions for Idle task'));
    fireEvent.click(screen.getByText('归档会话'));
    expect(onArchiveSession).toHaveBeenCalledWith('session_idle');

    fireEvent.click(screen.getByLabelText('Session actions for Idle task'));
    fireEvent.click(screen.getByText('永久删除'));
    expect(onDeleteSession).toHaveBeenCalledWith('session_idle');
    expect(screen.queryByLabelText('Session actions for Personal Agent · Main')).not.toBeInTheDocument();
  });

  it('expands and collapses project groups', () => {
    render(<SessionHistoryPanel history={historyFixture()} currentProjectPath="C:/repo" />);

    expect(screen.getByText('Implement agent history')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Collapse project repo'));
    expect(screen.queryByText('Implement agent history')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Expand project repo'));
    expect(screen.getByText('Implement agent history')).toBeInTheDocument();
  });

  it('keeps expansion state on backend canonical project identity', () => {
    const history = historyFixture();
    history.current_project_path = null;
    history.projects[0].is_current = false;
    history.projects[0].has_running = false;
    history.projects[0].project_key = 'c:/repo';
    const { rerender } = render(<SessionHistoryPanel history={history} currentProjectPath={null} />);

    fireEvent.click(screen.getByLabelText('Expand project repo'));
    expect(screen.getByText('Implement agent history')).toBeInTheDocument();

    const refreshed = historyFixture();
    refreshed.current_project_path = null;
    refreshed.projects[0].is_current = false;
    refreshed.projects[0].has_running = false;
    refreshed.projects[0].path = 'C:/repo/nested';
    refreshed.projects[0].canonical_path = 'C:/repo';
    refreshed.projects[0].project_key = 'c:/repo';
    rerender(<SessionHistoryPanel history={refreshed} currentProjectPath={null} />);

    expect(screen.getByText('Implement agent history')).toBeInTheDocument();
  });

  it('opens project action menu and emits menu actions', () => {
    const onProjectAction = vi.fn();
    render(
      <SessionHistoryPanel
        history={historyFixture()}
        currentProjectPath="C:/repo"
        onProjectAction={onProjectAction}
      />,
    );

    fireEvent.click(screen.getByLabelText('Project actions for repo'));

    expect(screen.getByText('置顶项目')).toBeInTheDocument();
    expect(screen.getByText('在资源管理器中打开')).toBeInTheDocument();
    expect(screen.getByText('创建永久工作树')).toBeInTheDocument();
    expect(screen.getByText('重命名项目')).toBeInTheDocument();
    expect(screen.getByText('归档会话')).toBeInTheDocument();
    expect(screen.getByText('移除')).toBeInTheDocument();

    fireEvent.click(screen.getByText('置顶项目'));
    expect(onProjectAction).toHaveBeenCalledWith('pin', expect.objectContaining({ path: 'C:/repo' }));
  });

  it('opens the same project menu from right click and supports unpin label', () => {
    const history = historyFixture();
    history.projects[0].is_pinned = true;
    const onProjectAction = vi.fn();

    render(
      <SessionHistoryPanel
        history={history}
        currentProjectPath="C:/repo"
        onProjectAction={onProjectAction}
      />,
    );

    fireEvent.contextMenu(screen.getByText('repo'));
    fireEvent.click(screen.getByText('取消置顶'));

    expect(onProjectAction).toHaveBeenCalledWith('unpin', expect.objectContaining({ path: 'C:/repo' }));
  });
});
