import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ArtifactPanel } from '../../components/ArtifactPanel/ArtifactPanel';
import type { AutomationSnapshot, AutomationTrace } from '../../types';

const png =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=';

describe('Automation Inspector', () => {
  it('renders snapshot elements and supports refresh actions', () => {
    const observe = vi.fn();
    const snapshot: AutomationSnapshot = {
      snapshot_id: 'snap-1',
      source: 'browser',
      timestamp: 1,
      title: 'Demo page',
      viewport: { width: 100, height: 100 },
      screenshot: { base64: png, width: 100, height: 100 },
      elements: [{
        id: 'browser:dom:1',
        source: 'browser',
        role: 'button',
        name: 'Submit',
        bbox: { x: 10, y: 10, width: 20, height: 10 },
      }],
      element_count: 1,
    };

    render(
      <ArtifactPanel
        artifacts={[]}
        isRunning={false}
        latestToolCall={null}
        automationSnapshots={[snapshot]}
        automationActions={[]}
        automationTraces={[]}
        automationReplayStatus={null}
        onAutomationObserve={observe}
      />,
    );

    expect(screen.getByText('Demo page')).toBeInTheDocument();
    expect(screen.getByText('Submit')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Desktop'));
    expect(observe).toHaveBeenCalledWith('desktop');
  });

  it('renders traces and calls replay', () => {
    const replay = vi.fn();
    const trace: AutomationTrace = {
      trace_id: 'trace-1',
      source: 'desktop',
      actions: [{
        action_id: 'act-1',
        type: 'click',
        source: 'desktop',
        status: 'success',
        duration_ms: 42,
      }],
    };

    render(
      <ArtifactPanel
        artifacts={[]}
        isRunning={false}
        latestToolCall={null}
        automationSnapshots={[]}
        automationActions={trace.actions}
        automationTraces={[trace]}
        automationReplayStatus={null}
        onAutomationReplay={replay}
      />,
    );

    fireEvent.click(screen.getByText('回放'));
    expect(screen.getByText('trace-1')).toBeInTheDocument();
    const traceRow = screen.getByText('trace-1').closest('div')!.parentElement!;
    fireEvent.click(within(traceRow).getByTitle('Replay trace'));
    expect(replay).toHaveBeenCalledWith('trace-1');
  });
});
