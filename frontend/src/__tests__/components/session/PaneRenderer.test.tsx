import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PaneRenderer } from '../../../components/session/PaneRenderer';
import type { LeafNode, PaneNode } from '../../../components/session/PaneTypes';
import { DEFAULT_AGENT_PROFILES } from '../../../lib/agentProfiles';
import type { Team } from '../../../lib/teamStore';

vi.mock('../../../components/session/SessionView', async () => {
  const React = await import('react');
  return {
    SessionView: React.forwardRef((props: any, ref: any) => {
      React.useImperativeHandle(ref, () => ({}));
      React.useEffect(() => {
        if (!props.isFocused) return;
        props.onSnapshot({
          sessionId: props.sessionId,
          projectPath: null,
          agentType: props.agentType,
          isRunning: false,
          isConnected: false,
          chatMode: 'agent',
          thinkingIntensity: 'medium',
          planState: { mode: 'agent', phase: 'idle', goal: '', draft: '', questions: [], todos: [], decisions: {}, approved: false },
          artifacts: [],
          editorGroups: [{ id: 'main', activeFileId: null, openFiles: [] }],
          activeEditorGroup: 'main',
          latestToolCall: null,
          fileEdits: [],
          toolCalls: [],
          runEvents: [],
        }, {});
      }, [props.agentType, props.isFocused, props.onSnapshot, props.sessionId]);
      return (
        <div
          data-testid={`session-${props.sessionId}`}
          data-team-id={props.teamId || ''}
          data-assistant-display-name={props.assistantDisplayName || ''}
          onClick={props.onFocus}
        >
          {props.sessionId}
        </div>
      );
    }),
  };
});

function leaf(id: string, paneId = `pane_${id}`, sessionId = `session_${id}`): LeafNode {
  return {
    type: 'leaf',
    id,
    pane: { id: paneId, sessionId, model: 'gpt-test', agentType: 'personal', role: 'desktop-agent' },
  };
}

function renderPane(node: PaneNode, overrides: Partial<React.ComponentProps<typeof PaneRenderer>> = {}) {
  const props: React.ComponentProps<typeof PaneRenderer> = {
    node,
    focusedLeafId: 'a',
    onFocus: vi.fn(),
    onMinimizePane: vi.fn(),
    onClosePane: vi.fn(),
    onSplit: vi.fn(),
    onMoveSession: vi.fn(),
    onSplitResize: vi.fn(),
    teams: [],
    onJoinTeam: vi.fn(),
    onCreateTeam: vi.fn((name: string): Team => ({ id: `team_${name}`, name, color: '#3b82f6', memberPaneIds: [], createdAt: 1 })),
    onLeaveTeam: vi.fn(),
    sessionViewRefs: { current: new Map() },
    currentProject: null,
    currentModel: 'gpt-test',
    currentAgentType: 'personal',
    currentRole: 'desktop-agent',
    models: [
      { id: 'gpt-test', name: 'GPT Test', provider: 'test', vision: false, context: 1 },
      { id: 'kimi-for-coding', name: 'Kimi Coding', provider: 'kimi', vision: true, context: 256000 },
    ],
    onModelChange: vi.fn(),
    onSnapshot: vi.fn(),
    onCommand: vi.fn(),
    runAction: vi.fn(async () => undefined),
    openRunWorktree: vi.fn(async () => undefined),
    handleOpenFileFromPanel: vi.fn(),
    handleOpenFileFromPanelWithLine: vi.fn(),
    ...overrides,
  };
  return { ...render(<PaneRenderer {...props} />), props };
}

describe('PaneRenderer', () => {
  it('keeps close buttons clickable while only the title area is draggable', () => {
    const root: PaneNode = { type: 'split', id: 'root', direction: 'horizontal', children: [leaf('a'), leaf('b')], sizes: [50, 50] };
    const onClosePane = vi.fn();

    renderPane(root, { onClosePane });

    fireEvent.pointerDown(screen.getAllByLabelText('Close pane')[1]);
    fireEvent.click(screen.getAllByLabelText('Close pane')[1]);

    expect(onClosePane).toHaveBeenCalledWith('b');
  });

  it('creates a coding split session from the plus button with explicit placement', () => {
    const onSplit = vi.fn();

    renderPane(leaf('a'), { onSplit });

    fireEvent.click(screen.getByLabelText('New Coding Session in Split Pane'));

    expect(onSplit).toHaveBeenCalledWith('a', 'horizontal', { placement: 'after', agentType: 'coding' });
  });

  it('minimizes a pane without closing it', () => {
    const onMinimizePane = vi.fn();
    const onClosePane = vi.fn();

    renderPane(leaf('a'), { onMinimizePane, onClosePane });

    fireEvent.click(screen.getByLabelText('Minimize pane'));

    expect(onMinimizePane).toHaveBeenCalledWith('a');
    expect(onClosePane).not.toHaveBeenCalled();
  });

  it('starts pane drags from the drag handle and includes session metadata', () => {
    renderPane(leaf('a', 'pane-a', 'session-a'));
    const dataTransfer = {
      setData: vi.fn(),
      setDragImage: vi.fn(),
      effectAllowed: '',
    };

    fireEvent.dragStart(screen.getByLabelText('Drag pane'), { dataTransfer });

    expect(dataTransfer.setData).toHaveBeenCalledWith(
      'application/x-desktop-agent-pane',
      JSON.stringify({
        leafId: 'a',
        paneId: 'pane-a',
        sessionId: 'session-a',
        model: 'gpt-test',
        agentType: 'personal',
        role: 'desktop-agent',
      }),
    );
  });

  it('shows agent type, session title, and model in the pane header', () => {
    renderPane(leaf('a', 'pane-a', 'session-a'), {
      sessionMetaById: {
        'session-a': {
          title: 'Planning work',
          model_id: 'gpt-test',
          agent_type: 'personal',
          is_primary: false,
        },
      },
    });

    expect(screen.getByText('Personal Agent')).toBeInTheDocument();
    expect(screen.getByText('Planning work')).toBeInTheDocument();
    expect(screen.getByDisplayValue('GPT Test')).toBeInTheDocument();
  });

  it('uses flatter chrome when rendered inside the floating chat dock', () => {
    renderPane(leaf('a', 'pane-a', 'session-a'), { chrome: 'floating' });

    const paneShell = screen.getByTestId('session-session-a').parentElement?.parentElement;
    expect(paneShell?.className).toContain('bg-transparent');
    expect(paneShell?.className).not.toContain('border rounded');
  });

  it('uses the Personal identity profile name instead of the selected role name', () => {
    renderPane(leaf('a', 'pane-a', 'session-a'), {
      agentProfiles: {
        ...DEFAULT_AGENT_PROFILES,
        personal: {
          ...DEFAULT_AGENT_PROFILES.personal,
          display_name: '镜与刃',
          source: 'IDENTITY.md',
        },
      },
      roleDisplayNames: { 'desktop-agent': '桌面助手' },
    });

    expect(screen.getByText('镜与刃')).toBeInTheDocument();
    expect(screen.queryByText('桌面助手')).not.toBeInTheDocument();
    expect(screen.getByTestId('session-session-a')).toHaveAttribute('data-assistant-display-name', '镜与刃');
  });

  it('switches the pane model from the title bar selector', () => {
    const onModelChange = vi.fn();

    renderPane(leaf('a', 'pane-a', 'session-a'), { onModelChange });

    fireEvent.change(screen.getByLabelText('Pane model'), { target: { value: 'kimi-for-coding' } });

    expect(onModelChange).toHaveBeenCalledWith('a', 'kimi-for-coding');
  });

  it('forwards focused snapshots through nested split nodes', async () => {
    const onSnapshot = vi.fn();
    const nested: PaneNode = {
      type: 'split',
      id: 'root',
      direction: 'horizontal',
      children: [
        leaf('a'),
        {
          type: 'split',
          id: 'nested',
          direction: 'vertical',
          children: [leaf('b'), leaf('c')],
          sizes: [50, 50],
        },
      ],
      sizes: [50, 50],
    };

    renderPane(nested, { focusedLeafId: 'c', onSnapshot });

    await waitFor(() => {
      expect(onSnapshot).toHaveBeenCalledWith(
        expect.objectContaining({ sessionId: 'session_c' }),
        expect.anything(),
      );
    });
  });
});
