import { useState, useEffect, useCallback } from 'react';
import type { SidebarSection, AgentType } from '../types';

export type RightZone = 'workspace' | 'activity';
export type PanelLayout = Record<string, number>;

export const DEFAULT_MAIN_LAYOUT: PanelLayout = { center: 68, right: 32 };
export const DEFAULT_TERMINAL_LAYOUT: PanelLayout = { conversation: 76, terminal: 24 };
export const DEFAULT_SIDEBAR_WIDTH = 224;
export const MIN_SIDEBAR_WIDTH = 184;
export const MAX_SIDEBAR_WIDTH = 420;
export const DEFAULT_CHAT_OVERLAY_WIDTH = 560;
export const MIN_CHAT_OVERLAY_WIDTH = 380;
export const MAX_CHAT_OVERLAY_WIDTH = 2400;
const CHAT_OVERLAY_VIEWPORT_GUTTER = 48;

const REQUIRED_MAIN_KEYS = Object.keys(DEFAULT_MAIN_LAYOUT);
const REQUIRED_TERMINAL_KEYS = Object.keys(DEFAULT_TERMINAL_LAYOUT);
const DEFAULT_SIDEBAR_SECTION: SidebarSection = 'skills';
const SIDEBAR_SECTIONS: SidebarSection[] = [
  'personal', 'coding', 'skills', 'workspace', 'settings',
];

// Legacy 11-tab values, kept only to migrate persisted layout state.
type LegacyRightTab =
  | 'tools' | 'artifacts' | 'editor' | 'changes' | 'runs'
  | 'tests' | 'problems' | 'eval' | 'knowledge' | 'workflow' | 'mcp';

function mapLegacyTab(tab: unknown): RightZone | undefined {
  if (typeof tab !== 'string') return undefined;
  switch (tab as LegacyRightTab) {
    case 'editor':
    case 'artifacts':
      return 'workspace';
    case 'tools':
    case 'changes':
    case 'runs':
    case 'tests':
    case 'problems':
    case 'eval':
    case 'knowledge':
    case 'workflow':
    case 'mcp':
      return 'activity';
    default:
      return undefined;
  }
}

interface LayoutState {
  activeSection: SidebarSection;
  activeAgent: AgentType;
  showTerminal: boolean;
  rightZone: RightZone;
  rightPanelVisible: boolean;
  sidebarCollapsed: boolean;
  sidebarWidth: number;
  chatOverlayWidth: number;
  mainLayout: PanelLayout;
  terminalLayout: PanelLayout;
}

function normalizeLayout(value: unknown, fallback: PanelLayout, requiredKeys: string[]): PanelLayout {
  if (!value || typeof value !== 'object') return fallback;

  const next: PanelLayout = {};
  for (const key of requiredKeys) {
    const raw = (value as Record<string, unknown>)[key];
    const numeric = Number(raw);
    if (!Number.isFinite(numeric) || numeric < 0) return fallback;
    next[key] = numeric;
  }

  const total = requiredKeys.reduce((sum, key) => sum + next[key], 0);
  if (total <= 0) return fallback;
  return requiredKeys.reduce<PanelLayout>((acc, key) => {
    acc[key] = (next[key] / total) * 100;
    return acc;
  }, {});
}

function normalizeSidebarSection(value: unknown): SidebarSection {
  if (value === 'tools') return 'skills';
  if (value === 'knowledge') return 'settings';
  if (typeof value === 'string' && SIDEBAR_SECTIONS.includes(value as SidebarSection)) {
    return value as SidebarSection;
  }
  return DEFAULT_SIDEBAR_SECTION;
}

function normalizeSidebarWidth(value: unknown): number {
  const width = Number(value);
  if (!Number.isFinite(width)) return DEFAULT_SIDEBAR_WIDTH;
  return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, width));
}

function normalizeChatOverlayWidth(value: unknown): number {
  const width = Number(value);
  if (!Number.isFinite(width)) return DEFAULT_CHAT_OVERLAY_WIDTH;
  const viewportLimit =
    typeof window === 'undefined'
      ? MAX_CHAT_OVERLAY_WIDTH
      : Math.max(MIN_CHAT_OVERLAY_WIDTH, window.innerWidth - CHAT_OVERLAY_VIEWPORT_GUTTER);
  return Math.min(viewportLimit, Math.max(MIN_CHAT_OVERLAY_WIDTH, width));
}

function loadLayout(): LayoutState {
  try {
    const raw = localStorage.getItem('desktop-agent-layout');
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        activeSection: normalizeSidebarSection(parsed.activeSection),
        activeAgent: (parsed.activeAgent as AgentType) || 'personal',
        showTerminal: parsed.showTerminal ?? true,
        rightZone: parsed.rightZone ?? mapLegacyTab(parsed.rightTab) ?? 'workspace',
        rightPanelVisible: parsed.rightPanelVisible ?? true,
        sidebarCollapsed: parsed.sidebarCollapsed ?? false,
        sidebarWidth: normalizeSidebarWidth(parsed.sidebarWidth),
        chatOverlayWidth: normalizeChatOverlayWidth(parsed.chatOverlayWidth),
        mainLayout: normalizeLayout(parsed.mainLayout, DEFAULT_MAIN_LAYOUT, REQUIRED_MAIN_KEYS),
        terminalLayout: normalizeLayout(parsed.terminalLayout, DEFAULT_TERMINAL_LAYOUT, REQUIRED_TERMINAL_KEYS),
      };
    }
  } catch { /* ignore */ }
  return {
    activeSection: DEFAULT_SIDEBAR_SECTION,
    activeAgent: 'personal',
    showTerminal: true,
    rightZone: 'workspace',
    rightPanelVisible: true,
    sidebarCollapsed: false,
    sidebarWidth: DEFAULT_SIDEBAR_WIDTH,
    chatOverlayWidth: DEFAULT_CHAT_OVERLAY_WIDTH,
    mainLayout: DEFAULT_MAIN_LAYOUT,
    terminalLayout: DEFAULT_TERMINAL_LAYOUT,
  };
}

export function useLayoutState() {
  const [state, setState] = useState<LayoutState>(loadLayout);

  useEffect(() => {
    try {
      localStorage.setItem('desktop-agent-layout', JSON.stringify(state));
    } catch { /* ignore */ }
  }, [state]);

  const setActiveSection = useCallback((value: SidebarSection) => {
    setState((state) => ({ ...state, activeSection: value }));
  }, []);

  const setActiveAgent = useCallback((value: AgentType) => {
    setState((state) => ({ ...state, activeAgent: value }));
  }, []);

  const setShowTerminal = useCallback((value: boolean | ((previous: boolean) => boolean)) => {
    setState((state) => ({ ...state, showTerminal: typeof value === 'function' ? value(state.showTerminal) : value }));
  }, []);

  const toggleTerminal = useCallback(() => {
    setState((state) => ({ ...state, showTerminal: !state.showTerminal }));
  }, []);

  const setRightZone = useCallback((value: RightZone) => {
    setState((state) => ({ ...state, rightZone: value }));
  }, []);

  const setRightPanelVisible = useCallback((value: boolean | ((previous: boolean) => boolean)) => {
    setState((state) => ({ ...state, rightPanelVisible: typeof value === 'function' ? value(state.rightPanelVisible) : value }));
  }, []);

  const toggleRightPanel = useCallback(() => {
    setState((state) => ({ ...state, rightPanelVisible: !state.rightPanelVisible }));
  }, []);

  const setSidebarCollapsed = useCallback((value: boolean | ((previous: boolean) => boolean)) => {
    setState((state) => ({ ...state, sidebarCollapsed: typeof value === 'function' ? value(state.sidebarCollapsed) : value }));
  }, []);

  const toggleSidebar = useCallback(() => {
    setState((state) => ({ ...state, sidebarCollapsed: !state.sidebarCollapsed }));
  }, []);

  const setSidebarWidth = useCallback((value: number) => {
    setState((state) => ({ ...state, sidebarWidth: normalizeSidebarWidth(value) }));
  }, []);

  const setChatOverlayWidth = useCallback((value: number) => {
    setState((state) => ({ ...state, chatOverlayWidth: normalizeChatOverlayWidth(value) }));
  }, []);

  const setMainLayout = useCallback((layout: PanelLayout) => {
    setState((state) => ({
      ...state,
      mainLayout: normalizeLayout(layout, state.mainLayout, REQUIRED_MAIN_KEYS),
    }));
  }, []);

  const setTerminalLayout = useCallback((layout: PanelLayout) => {
    setState((state) => ({
      ...state,
      terminalLayout: normalizeLayout(layout, state.terminalLayout, REQUIRED_TERMINAL_KEYS),
    }));
  }, []);

  const resetLayout = useCallback(() => {
    setState({
      activeSection: DEFAULT_SIDEBAR_SECTION,
      activeAgent: 'personal',
      showTerminal: true,
      rightZone: 'workspace',
      rightPanelVisible: true,
      sidebarCollapsed: false,
      sidebarWidth: DEFAULT_SIDEBAR_WIDTH,
      chatOverlayWidth: DEFAULT_CHAT_OVERLAY_WIDTH,
      mainLayout: DEFAULT_MAIN_LAYOUT,
      terminalLayout: DEFAULT_TERMINAL_LAYOUT,
    });
  }, []);

  return {
    ...state,
    setActiveSection,
    setActiveAgent,
    setShowTerminal,
    toggleTerminal,
    setRightZone,
    setRightPanelVisible,
    toggleRightPanel,
    setSidebarCollapsed,
    toggleSidebar,
    setSidebarWidth,
    setChatOverlayWidth,
    setMainLayout,
    setTerminalLayout,
    resetLayout,
  };
}
