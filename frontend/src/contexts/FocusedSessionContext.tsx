import React, { createContext, useContext, useCallback, useRef } from 'react';
import type { ChatMessage, ToolCall, FileEdit, RunEvent, ArtifactItem, EditorGroup, PlanState, ClientChatMode, ThinkingIntensity, AgentType, ContextUsage, ConversationCheckpoint } from '../types';

// ---- Types ----

export interface SessionSnapshot {
  sessionId: string;
  agentType: AgentType;
  isRunning: boolean;
  isConnected: boolean;
  chatMode: ClientChatMode;
  thinkingIntensity: ThinkingIntensity;
  planState: PlanState;
  contextUsage?: ContextUsage | null;
  checkpoints?: ConversationCheckpoint[];
  suggestAgentSwitch?: { from: string; to: string; reason: string } | null;
  // Per-session derived (changes relatively slowly)
  artifacts: ArtifactItem[];
  editorGroups: EditorGroup[];
  activeEditorGroup: string;
  latestToolCall: ToolCall | null;
  fileEdits: FileEdit[];
  toolCalls: ToolCall[];
  runEvents: RunEvent[];
}
export interface SessionActions {
  sendMessage: (text: string, imageBase64?: string, overrides?: { chatMode?: ClientChatMode; thinkingIntensity?: ThinkingIntensity }) => void;
  clearSession: () => void;
  compactSession: (force?: boolean, focus?: string) => void;
  loadCheckpoints: () => Promise<ConversationCheckpoint[]>;
  rewindToCheckpoint: (checkpointId: string) => void;
  stopRunning: () => void;
  retryLast: () => void;
  switchModel: (modelId: string) => void;
  executeToolDirect: (toolName: string, args: any) => void;
  addTerminalLog: (msg: string) => void;
  approvePlan: () => void;
  buildPlan: () => void;
  rejectPlan: () => void;
  updatePlanDecision: (questionId: string, selected: string[]) => void;
  onSelectFileInEditor: (groupId: string, fileId: string) => void;
  onCloseFileInEditor: (groupId: string, fileId: string) => void;
  onFileContentChange: (groupId: string, fileId: string, content: string) => void;
  onSaveFile: (groupId: string, fileId: string, content: string) => void;
  saveInputDraft: (text: string) => Promise<void>;
  loadInputDraft: () => Promise<string | undefined>;
  clearInputDraft: () => Promise<void>;
  runAction: (runId: string, action: 'apply' | 'merge' | 'discard') => Promise<void>;
  openRunWorktree: (runId: string) => Promise<void>;
  handleOpenFileFromPanel: (path: string) => void;
  handleOpenFileFromPanelWithLine: (path: string, line?: number) => void;
}

const NOOP_ACTIONS: SessionActions = {
  sendMessage: () => {},
  clearSession: () => {},
  compactSession: () => {},
  loadCheckpoints: async () => [],
  rewindToCheckpoint: () => {},
  stopRunning: () => {},
  retryLast: () => {},
  switchModel: () => {},
  executeToolDirect: () => {},
  addTerminalLog: () => {},
  approvePlan: () => {},
  buildPlan: () => {},
  rejectPlan: () => {},
  updatePlanDecision: () => {},
  onSelectFileInEditor: () => {},
  onCloseFileInEditor: () => {},
  onFileContentChange: () => {},
  onSaveFile: () => {},
  saveInputDraft: async () => {},
  loadInputDraft: async () => undefined,
  clearInputDraft: async () => {},
  runAction: async () => {},
  openRunWorktree: async () => {},
  handleOpenFileFromPanel: () => {},
  handleOpenFileFromPanelWithLine: () => {},
};

// ---- Context (split data/actions for perf) ----

const FocusedDataContext = createContext<SessionSnapshot | null>(null);
const FocusedActionsContext = createContext<SessionActions>(NOOP_ACTIONS);

export function useFocusedData(): SessionSnapshot | null {
  return useContext(FocusedDataContext);
}

export function useFocusedActions(): SessionActions {
  return useContext(FocusedActionsContext);
}

// ---- Provider ----

export const FocusedDataProvider = FocusedDataContext.Provider;
export const FocusedActionsProvider = FocusedActionsContext.Provider;
