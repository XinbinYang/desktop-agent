export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  vision: boolean;
  context: number;
}

export interface RoleInfo {
  id: string;
  name: string;
  description: string;
  isBuiltin: boolean;
}

export interface ProviderSettings {
  name: string;
  base_url: string;
  api_key_masked: string;
  api_key_configured?: boolean;
  models: ModelInfo[];
}

export interface AppSettings {
  default_model: string;
  default_provider: string;
  max_iterations: number;
  auto_approve: boolean;
  screenshot_on_step: boolean;
  sandbox_mode: string;
}

export interface SettingsResponse {
  providers: Record<string, ProviderSettings>;
  settings: AppSettings;
}

export type ArtifactType = 'web' | 'image' | 'data' | 'code' | 'terminal' | 'video';

export interface ArtifactItem {
  id: string;
  type: ArtifactType;
  title: string;
  content?: string;
  url?: string;
  base64?: string;
  timestamp: number;
  sourceTool: string;
}

export interface WorkerEvent {
  workerId: string;
  type: 'worker_start' | 'worker_content' | 'worker_tool_call' | 'worker_done';
  task?: string;
  profile?: string;
  modelId?: string;
  runId?: string;
  parentToolCallId?: string;
  text?: string;
  toolName?: string;
  toolArgs?: Record<string, any>;
  toolResult?: string;
  toolDurationMs?: number;
  status?: 'running' | 'completed' | 'failed' | 'cancelled' | 'max_iterations_reached';
  result?: string;
  iterations?: number;
  durationMs?: number;
}

export interface FileEdit {
  path: string;
  operation: 'create' | 'modify' | 'delete' | string;
  old_text?: string;
  new_text?: string;
  unified_diff: string;
  stats: {
    added: number;
    removed: number;
  };
  truncated: boolean;
  run_id?: string;
  tool_call_id?: string;
  worker_id?: string;
  parent_tool_call_id?: string;
  timestamp?: number;
}

export interface ToolCall {
  name: string;
  args: Record<string, any>;
  result: string;
  timestamp: number;
  runId?: string;
  toolCallId?: string;
  durationMs?: number;
  workerEvents?: WorkerEvent[];
}

export type AssistantBlock =
  | { type: 'thinking'; text: string; timestamp: number }
  | { type: 'text'; text: string; timestamp: number }
  | { type: 'file_edit'; edit: FileEdit; timestamp: number }
  | {
      type: 'tool_call';
      name: string;
      args: Record<string, any>;
      result?: string;
      status: 'running' | 'success' | 'error';
      toolCallId?: string;
      durationMs?: number;
      workerEvents?: WorkerEvent[];
      timestamp: number;
    }
  | { type: 'image'; base64: string; timestamp: number };

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  imageBase64?: string;
  isTool: boolean;
  reasoning?: string;
  skill?: string;
  blocks?: AssistantBlock[];
  turnComplete?: boolean;
}

export interface ProjectInfo {
  path: string;
  name: string;
  git_branch?: string;
  git_remote?: string;
  git_ahead?: number;
  git_behind?: number;
  git_modified?: number;
  git_untracked?: number;
  git_staged?: number;
  last_opened: string;
}

export interface FileNode {
  name: string;
  type: 'file' | 'dir';
  path: string;
  extension?: string;
  children?: FileNode[];
}

export interface OpenFile {
  id: string;
  path: string;
  name: string;
  content: string;
  language: string;
  isModified?: boolean;
  hasConflict?: boolean;
  isPinned?: boolean;
}

export interface EditorGroup {
  id: 'main' | 'secondary';
  activeFileId: string | null;
  openFiles: OpenFile[];
}

export type SidebarSection = 'tools' | 'project' | 'sessions' | 'knowledge' | 'settings';

export interface KnowledgeDoc {
  source_path: string;
  chunk_count: number;
  last_indexed: number;
}

export interface KnowledgeSearchResult {
  chunk_id: string;
  source_path: string;
  content: string;
  score: number;
}

export interface WorkflowData {
  id: string;
  name: string;
  description: string;
  created_at: string;
  variables: { name: string; default: string; description: string }[];
  steps: { step_id: string; tool_name: string; args: Record<string, any>; param_args?: Record<string, any> }[];
}

export interface WS_EVENT {
  type: 'content' | 'reasoning' | 'tool_call' | 'image' | 'file_edit' | 'status' | 'error' | 'done' | 'cleared' | 'interrupted' | 'tool_result' | 'worker_start' | 'worker_content' | 'worker_tool_call' | 'worker_done';
  data: any;
}

declare global {
  interface Window {
    electronAPI: {
      selectFolder: () => Promise<string | undefined>;
      selectFile: () => Promise<string | undefined>;
      getAppVersion: () => Promise<string>;
      getAuthToken: () => Promise<string>;
      onNewSession: (cb: () => void) => () => void;
    };
  }
}
