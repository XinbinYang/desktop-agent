import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_MAIN_LAYOUT,
  DEFAULT_SIDEBAR_WIDTH,
  DEFAULT_TERMINAL_LAYOUT,
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  useLayoutState,
} from '../../hooks/useLayoutState';

describe('useLayoutState', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('persists main and terminal layouts', () => {
    const { result } = renderHook(() => useLayoutState());

    act(() => {
      result.current.setMainLayout({ center: 60, right: 40 });
      result.current.setTerminalLayout({ conversation: 70, terminal: 30 });
    });

    const stored = JSON.parse(localStorage.getItem('desktop-agent-layout') || '{}');
    expect(stored.mainLayout).toEqual({ center: 60, right: 40 });
    expect(stored.terminalLayout).toEqual({ conversation: 70, terminal: 30 });
  });

  it('persists and clamps sidebar width', () => {
    const { result } = renderHook(() => useLayoutState());

    act(() => {
      result.current.setSidebarWidth(320);
    });
    expect(result.current.sidebarWidth).toBe(320);

    act(() => {
      result.current.setSidebarWidth(999);
    });
    expect(result.current.sidebarWidth).toBe(MAX_SIDEBAR_WIDTH);

    act(() => {
      result.current.setSidebarWidth(1);
    });
    expect(result.current.sidebarWidth).toBe(MIN_SIDEBAR_WIDTH);

    const stored = JSON.parse(localStorage.getItem('desktop-agent-layout') || '{}');
    expect(stored.sidebarWidth).toBe(MIN_SIDEBAR_WIDTH);
  });

  it('uses skills as the default sidebar section', () => {
    const { result } = renderHook(() => useLayoutState());
    expect(result.current.activeSection).toBe('skills');
  });

  it('migrates legacy tools sidebar section to skills', () => {
    localStorage.setItem('desktop-agent-layout', JSON.stringify({
      activeSection: 'tools',
      activeAgent: 'personal',
    }));

    const { result } = renderHook(() => useLayoutState());
    expect(result.current.activeSection).toBe('skills');
  });

  it('normalizes invalid persisted layouts and resets to defaults', () => {
    localStorage.setItem('desktop-agent-layout', JSON.stringify({
      activeSection: 'sessions',
      activeAgent: 'coding',
      showTerminal: false,
      rightPanelVisible: false,
      mainLayout: { center: 0, right: 0 },
      terminalLayout: { conversation: 10 },
    }));

    const { result } = renderHook(() => useLayoutState());

    expect(result.current.mainLayout).toEqual(DEFAULT_MAIN_LAYOUT);
    expect(result.current.terminalLayout).toEqual(DEFAULT_TERMINAL_LAYOUT);

    act(() => {
      result.current.resetLayout();
    });

    expect(result.current.showTerminal).toBe(true);
    expect(result.current.rightPanelVisible).toBe(true);
    expect(result.current.activeSection).toBe('skills');
    expect(result.current.sidebarWidth).toBe(DEFAULT_SIDEBAR_WIDTH);
    expect(result.current.mainLayout).toEqual(DEFAULT_MAIN_LAYOUT);
    expect(result.current.terminalLayout).toEqual(DEFAULT_TERMINAL_LAYOUT);
  });
});
