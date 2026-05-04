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
  models: ModelInfo[];
}

export interface AppSettings {
  default_model: string;
  default_provider: string;
  max_iterations: number;
  auto_approve: boolean;
  screenshot_on_step: boolean;
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

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  imageBase64?: string;
  isTool: boolean;
  reasoning?: string;
  skill?: string;
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
  isPinned?: boolean;
}

export interface EditorGroup {
  id: 'main' | 'secondary';
  activeFileId: string | null;
  openFiles: OpenFile[];
}

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
  type: 'content' | 'reasoning' | 'tool_call' | 'image' | 'status' | 'error' | 'done' | 'cleared' | 'interrupted' | 'tool_result' | 'worker_start' | 'worker_content' | 'worker_tool_call' | 'worker_done';
  data: any;
}

declare global {
  interface Window {
    electronAPI: {
      selectFolder: () => Promise<string | undefined>;
      selectFile: () => Promise<string | undefined>;
      getAppVersion: () => Promise<string>;
      onNewSession: (cb: () => void) => () => void;
    };
  }
}
