import { useState, useEffect, useCallback } from 'react';
import type { SidebarSection } from '../types';

type RightTab = 'tools' | 'artifacts' | 'editor' | 'changes' | 'runs' | 'tests' | 'problems' | 'eval' | 'knowledge' | 'workflow' | 'mcp';

interface LayoutState {
  activeSection: SidebarSection;
  showTerminal: boolean;
  rightTab: RightTab;
  rightPanelVisible: boolean;
  sidebarCollapsed: boolean;
}

function loadLayout(): LayoutState {
  try {
    const raw = localStorage.getItem('desktop-agent-layout');
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        activeSection: parsed.activeSection || 'tools',
        showTerminal: parsed.showTerminal ?? true,
        rightTab: parsed.rightTab || 'tools',
        rightPanelVisible: parsed.rightPanelVisible ?? true,
        sidebarCollapsed: parsed.sidebarCollapsed ?? false,
      };
    }
  } catch { /* ignore */ }
  return {
    activeSection: 'tools',
    showTerminal: true,
    rightTab: 'tools',
    rightPanelVisible: true,
    sidebarCollapsed: false,
  };
}

export function useLayoutState() {
  const [state, setState] = useState<LayoutState>(loadLayout);

  useEffect(() => {
    try {
      localStorage.setItem('desktop-agent-layout', JSON.stringify(state));
    } catch { /* ignore */ }
  }, [state]);

  const setActiveSection = useCallback((v: SidebarSection) => setState((s) => ({ ...s, activeSection: v })), []);
  const setShowTerminal = useCallback((v: boolean | ((p: boolean) => boolean)) =>
    setState((s) => ({ ...s, showTerminal: typeof v === 'function' ? v(s.showTerminal) : v })), []);
  const toggleTerminal = useCallback(() => setState((s) => ({ ...s, showTerminal: !s.showTerminal })), []);
  const setRightTab = useCallback((v: RightTab) => setState((s) => ({ ...s, rightTab: v })), []);
  const setRightPanelVisible = useCallback((v: boolean | ((p: boolean) => boolean)) =>
    setState((s) => ({ ...s, rightPanelVisible: typeof v === 'function' ? v(s.rightPanelVisible) : v })), []);
  const toggleRightPanel = useCallback(() => setState((s) => ({ ...s, rightPanelVisible: !s.rightPanelVisible })), []);
  const setSidebarCollapsed = useCallback((v: boolean | ((p: boolean) => boolean)) =>
    setState((s) => ({ ...s, sidebarCollapsed: typeof v === 'function' ? v(s.sidebarCollapsed) : v })), []);
  const toggleSidebar = useCallback(() => setState((s) => ({ ...s, sidebarCollapsed: !s.sidebarCollapsed })), []);

  const resetLayout = useCallback(() => {
    setState({
      activeSection: 'tools',
      showTerminal: true,
      rightTab: 'tools',
      rightPanelVisible: true,
      sidebarCollapsed: false,
    });
  }, []);

  return {
    ...state,
    setActiveSection,
    setShowTerminal,
    toggleTerminal,
    setRightTab,
    setRightPanelVisible,
    toggleRightPanel,
    setSidebarCollapsed,
    toggleSidebar,
    resetLayout,
  };
}
