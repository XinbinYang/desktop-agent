import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PaneRenderer } from '../../../components/session/PaneRenderer';
import type { LeafNode, PaneNode } from '../../../components/session/PaneTypes';
import type { Team } from '../../../lib/teamStore';

vi.mock('../../../components/session/SessionView', async () => {
  const React = await import('react');
  return {
    SessionView: React.forwardRef((props: any, ref: any) => {
      React.useImperativeHandle(ref, () => ({}));
      return (
        <div data-testid={`session-${props.sessionId}`} data-team-id={props.teamId || ''} onClick={props.onFocus}>
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

  it('splits to the right from the plus button with explicit placement', () => {
    const onSplit = vi.fn();

    renderPane(leaf('a'), { onSplit });

    fireEvent.click(screen.getByLabelText('Split pane right'));

    expect(onSplit).toHaveBeenCalledWith('a', 'horizontal', { placement: 'after' });
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
});
