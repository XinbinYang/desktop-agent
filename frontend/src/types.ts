export interface SuggestedModel {
  id: string;
  suggested_name: string;
  suggested_context: number;
  vision: boolean;
}

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
  litellm_provider: string;
  models: ModelInfo[];
}

export interface AppSettings {
  default_model: string;
  default_provider: string;
  max_iterations: number;
  auto_approve: boolean;
  screenshot_on_step: boolean;
  sandbox_mode: string;
  thinking_intensity_default?: ThinkingIntensity;
  collaboration_mode?: "serial" | "parallel" | "hybrid";
  max_parallel_agents?: number;
  review_gate_enabled?: boolean;
}

export interface CodingAgentSettings {
  enabled: boolean;
  default_execution_mode: "worktree" | "current_dir" | string;
  max_fix_rounds: number;
  max_parallel_workers: number;
  require_verification: boolean;
  require_review: boolean;
  auto_generate_repo_map: boolean;
}

export interface SettingsResponse {
  providers: Record<string, ProviderSettings>;
  settings: AppSettings;
  coding_agent?: CodingAgentSettings;
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

export interface ToolSummary {
  total: number;
  success: number;
  error: number;
  running: number;
  toolBuckets: Array<{ label: string; count: number }>;
}

export interface RunEvent {
  id: string;
  type:
    | 'run_created'
    | 'context_pack'
    | 'guardrail_decision'
    | 'approval_required'
    | 'verification_start'
    | 'verification_result'
    | 'review_finding'
    | 'run_completed';
  runId?: string;
  timestamp: number;
  data: Record<string, any>;
}

export type ClientChatMode = "agent" | "plan";
export type ThinkingIntensity = "low" | "medium" | "high";

export interface PlanQuestionOption {
  id: string;
  label: string;
}

export interface PlanQuestion {
  id: string;
  prompt: string;
  allow_multiple?: boolean;
  options: PlanQuestionOption[];
  selected?: string[];
}

export type PlanTodoStatus = "pending" | "in_progress" | "completed" | "blocked" | "cancelled";

export interface PlanTodo {
  id: string;
  title: string;
  status: PlanTodoStatus;
  depends_on?: string[];
  owner?: string;
  parallel_group?: string;
  acceptance_criteria?: string;
}

export interface StructuredPlanStep {
  id: string;
  title: string;
  details?: string;
  depends_on?: string[];
  parallel_group?: string;
}

export interface StructuredPlanDraft {
  goal: string;
  assumptions: string[];
  steps: StructuredPlanStep[];
  todos: PlanTodo[];
  risks: string[];
  acceptance_criteria: string[];
}

export interface PlanState {
  mode: ClientChatMode;
  phase: "idle" | "clarifying" | "planning" | "awaiting_decision" | "awaiting_approval" | "approved_waiting_build" | "executing" | "completed";
  goal: string;
  draft: string;
  structured_plan?: StructuredPlanDraft | null;
  questions: PlanQuestion[];
  todos: PlanTodo[];
  decisions: Record<string, string[]>;
  approved: boolean;
  /** Server: full todos withheld until user answers clarification questions */
  pending_clarification?: boolean;
  /** Path to the rendered plan markdown file on disk */
  plan_file_path?: string | null;
  /** Markdown research notes from the exploration phase */
  research_notes?: string;
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
  toolSummary?: ToolSummary;
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

export interface ErrorData {
  category: string;       // ErrorCategory: auth, network, rate_limit, provider, timeout, context_length, sandbox, tool_failure, tool_not_found, validation, not_found, internal, unknown
  message: string;
  retryable: boolean;
  details?: Record<string, any>;
}

export interface WS_EVENT {
  type: 'content' | 'reasoning' | 'tool_call' | 'image' | 'file_edit' | 'status' | 'error' | 'done' | 'cleared' | 'interrupted' | 'tool_result' | 'history_snapshot' | 'worker_start' | 'worker_content' | 'worker_tool_call' | 'worker_done' | 'plan_status' | 'plan_draft' | 'plan_questions' | 'plan_approved_waiting_build' | 'build_started' | 'plan_rejected' | 'plan_file_ready' | 'todo_update' | 'run_created' | 'context_pack' | 'guardrail_decision' | 'approval_required' | 'verification_start' | 'verification_result' | 'review_finding' | 'run_completed' | 'chat_mode' | 'compacted' | 'model_switched';
  data: any;
}

/** Extract a display message from either a structured error or legacy flat error. */
export function errorMessage(data: any): string {
  if (typeof data === 'string') return data;
  if (data?.message) return data.message;
  return JSON.stringify(data);
}

/** Check whether an error event is retryable. */
export function isRetryableError(data: any): boolean {
  return !!(data?.retryable);
}

/** Get the error category, falling back to 'unknown'. */
export function errorCategory(data: any): string {
  return data?.category || 'unknown';
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
