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

export interface ContextUsage {
  session_id: string;
  model_id: string;
  model_context: number;
  estimated_tokens: number;
  used_tokens: number;
  output_tokens?: number;
  remaining_tokens: number;
  used_percent: number;
  exact: boolean;
  source: 'provider' | 'estimate' | string;
  status: 'ok' | 'warning' | 'critical' | string;
  breakdown: Record<string, number>;
  transcript_message_count?: number;
  context_message_count?: number;
  transcript_estimated_tokens?: number;
  context_estimated_tokens?: number;
  context_truncated?: boolean;
  compaction_active?: boolean;
  context_epoch?: number;
  archived_message_count?: number;
  context_reset_active?: boolean;
  compacted_through_checkpoint_id?: string;
  summarized_message_count?: number;
  unsummarized_context_truncated?: boolean;
}

export interface ConversationCheckpoint {
  id: string;
  message_id?: string;
  turn_id?: string;
  index: number;
  role: 'user';
  preview: string;
  created_at: number;
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
  default_model?: string;
  default_provider?: string;
  max_iterations: number;
  auto_approve: boolean;
  screenshot_on_step: boolean;
  sandbox_mode: string;
  thinking_intensity_default?: ThinkingIntensity;
  collaboration_mode?: "serial" | "parallel" | "hybrid";
  max_parallel_agents?: number;
  review_gate_enabled?: boolean;
}

export interface PersonalAgentSettings {
  model: string;
  thinking_intensity: ThinkingIntensity;
}

export interface CodingAgentSettings {
  enabled: boolean;
  default_execution_mode: "worktree" | "current_dir" | string;
  max_fix_rounds: number;
  max_parallel_workers: number;
  require_verification: boolean;
  require_review: boolean;
  auto_generate_repo_map: boolean;
  model: string;
  thinking_intensity: ThinkingIntensity;
}

export type WebSearchProvider = "auto" | "brave" | "tavily" | "serpapi" | "duckduckgo";

export interface WebSearchKeyStatus {
  api_key_masked: string;
  api_key_configured: boolean;
}

export interface WebSearchSettings {
  provider: WebSearchProvider;
  fallback_enabled: boolean;
  allow_private_network: boolean;
  providers: {
    brave: WebSearchKeyStatus;
    tavily: WebSearchKeyStatus;
    serpapi: WebSearchKeyStatus;
  };
}

export interface SettingsResponse {
  providers: Record<string, ProviderSettings>;
  settings: AppSettings;
  coding_agent?: CodingAgentSettings;
  personal_agent?: PersonalAgentSettings;
  web_search?: WebSearchSettings;
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

export interface AutomationBBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AutomationElement {
  id: string;
  source: 'browser' | 'desktop' | string;
  role: string;
  name?: string;
  text?: string;
  selector?: string;
  bbox: AutomationBBox;
  confidence?: number;
  attributes?: Record<string, any>;
}

export interface AutomationSnapshot {
  snapshot_id: string;
  session_id?: string;
  source: 'browser' | 'desktop' | string;
  timestamp: number;
  title?: string;
  url?: string;
  viewport: { width: number; height: number };
  screenshot?: {
    base64?: string;
    width?: number;
    height?: number;
    path?: string;
  };
  elements: AutomationElement[];
  element_count?: number;
  tool_call_id?: string;
}

export interface AutomationAction {
  action_id: string;
  type: 'click' | 'type' | 'key' | 'scroll' | string;
  source: 'browser' | 'desktop' | string;
  args?: Record<string, any>;
  status: 'running' | 'success' | 'error' | string;
  started_at?: number;
  duration_ms?: number;
  error?: string;
  before_snapshot_id?: string;
  after_snapshot_id?: string;
  resolved_element?: AutomationElement | null;
  locator_chain?: string[];
  tool_call_id?: string;
}

export interface AutomationTrace {
  trace_id: string;
  session_id?: string;
  source?: string;
  actions: AutomationAction[];
  created_at?: number;
  updated_at?: number;
  path?: string;
  tool_call_id?: string;
}

export interface AutomationReplayStatus {
  trace_id: string;
  status: 'running' | 'completed' | 'error' | string;
  from_step?: number;
  to_step?: number;
  events?: Array<{ step: number; status: string; output?: string }>;
  error?: string;
  tool_call_id?: string;
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

export interface KnowledgeContextSource {
  source_path: string;
  score: number;
  preview?: string;
}

export interface RunEvent {
  id: string;
  type:
    | 'run_created'
    | 'context_pack'
    | 'skills_matched'
    | 'skill_draft_ready'
    | 'guardrail_decision'
    | 'approval_required'
    | 'verification_start'
    | 'verification_result'
    | 'review_finding'
    | 'collaboration_run_created'
    | 'collaboration_task_update'
    | 'agent_message'
    | 'artifact_ready'
    | 'decision_required'
    | 'collaboration_run_completed'
    | 'run_completed';
  runId?: string;
  timestamp: number;
  data: Record<string, any>;
}

export interface ArtifactRef {
  id: string;
  type: string;
  title: string;
  url?: string;
  path?: string;
  content?: string;
  metadata?: Record<string, any>;
}

export interface ResultPacket {
  status: 'pass' | 'fail' | 'blocked';
  summary: string;
  details?: string;
  changed_files?: string[];
  tests_run?: string[];
  verification_passed?: boolean | null;
  review_passed?: boolean | null;
  assumptions?: string[];
  blockers?: string[];
  artifacts?: ArtifactRef[];
}

export interface CollaborationTask {
  task_id: string;
  run_id: string;
  owner: 'personal' | 'coding' | 'worker';
  mode: 'consult' | 'execute' | 'handoff';
  status: 'pending' | 'running' | 'completed' | 'failed' | 'blocked' | 'cancelled';
  packet: Record<string, any>;
  result?: ResultPacket | null;
  created_at: number;
  updated_at: number;
}

export interface CollaborationRun {
  run_id: string;
  session_id: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  source_agent: 'personal' | 'coding' | 'worker';
  target_agent: 'personal' | 'coding' | 'worker';
  mode: 'consult' | 'execute' | 'handoff';
  goal: string;
  project_path?: string;
  task_ids: string[];
  artifacts: ArtifactRef[];
  summary?: string;
  created_at: number;
  updated_at: number;
}

export interface AgentMention {
  id: string;
  label: string;
  agent_type: AgentType;
}

export interface AgentMessage {
  agent_type: AgentType;
  text: string;
  status?: string;
  run_id?: string;
  task_id?: string;
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

export interface PlanDecisionAnswer {
  question_id: string;
  selected: string[];
  other_text?: string;
  skipped?: boolean;
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

export interface CriticalFile {
  path: string;
  change?: string;
}

export interface StructuredPlanDraft {
  goal: string;
  context?: string;
  assumptions: string[];
  steps: StructuredPlanStep[];
  todos: PlanTodo[];
  risks: string[];
  acceptance_criteria: string[];
  critical_files?: CriticalFile[];
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
  decision_notes?: Record<string, string>;
  approved: boolean;
  /** Server: full todos withheld until user answers clarification questions */
  pending_clarification?: boolean;
  /** Path to the rendered plan markdown file on disk */
  plan_file_path?: string | null;
  /** Markdown research notes from the exploration phase */
  research_notes?: string;
}

export type TaskGuidanceStatus = "queued" | "applied" | "consumed" | "stale";

export interface TaskGuidanceItem {
  id: string;
  text: string;
  image_base64?: string | null;
  status: TaskGuidanceStatus;
  created_at: number;
  applied_at?: number | null;
  consumed_at?: number | null;
  truncated?: boolean;
}

export type AssistantBlock =
  | {
      type: 'thinking';
      text: string;
      timestamp: number;
      /** When the first reasoning token of this block arrived (frontend clock). */
      startedAt?: number;
      /** When this thinking block was sealed (a non-thinking block / turn end). */
      endedAt?: number;
      /** True once the thinking step has finished streaming. */
      complete?: boolean;
    }
  | { type: 'text'; text: string; timestamp: number }
  | { type: 'knowledge_context'; sources: KnowledgeContextSource[]; timestamp: number }
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
  | { type: 'image'; base64: string; timestamp: number }
  | { type: 'plan_questions'; questions: PlanQuestion[]; timestamp: number }
  | { type: 'plan_answers'; questions: PlanQuestion[]; answers: PlanDecisionAnswer[]; timestamp: number }
  | { type: 'plan_execution'; goal: string; todos: PlanTodo[]; timestamp: number }
  | {
      type: 'plan_draft';
      goal: string;
      draft: string;
      todos: PlanTodo[];
      structured_plan?: StructuredPlanDraft | null;
      timestamp: number;
    };

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  source?: string;
  noticeLevel?: 'success' | 'info' | 'warning' | 'error';
  messageId?: string;
  turnId?: string;
  checkpointId?: string;
  contextEpoch?: number;
  createdAt?: number;
  imageBase64?: string;
  rawContent?: unknown;
  attachmentCount?: number;
  isTool: boolean;
  reasoning?: string;
  skill?: string;
  agentType?: AgentType;
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
  has_children?: boolean;
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
  readOnly?: boolean;
  source?: 'project' | 'plan' | 'artifact';
}

export interface EditorGroup {
  id: 'main' | 'secondary';
  activeFileId: string | null;
  openFiles: OpenFile[];
}

export type AgentType = 'personal' | 'coding';
export type SidebarSection = 'personal' | 'coding' | 'skills' | 'workspace' | 'settings';

export interface SessionHistoryItem {
  id: string;
  title?: string;
  project_path?: string | null;
  model_id: string;
  role_id?: string;
  agent_type?: AgentType;
  message_count: number;
  updated_at?: number;
  is_primary?: boolean;
  archived_at?: string | null;
  is_running: boolean;
  active_connections: number;
  activity_state: 'idle' | 'running' | 'needs_input';
}

export interface SessionHistoryProject {
  path: string;
  canonical_path?: string;
  project_key?: string;
  name: string;
  display_name?: string | null;
  folder_name?: string;
  last_opened?: string | null;
  is_current: boolean;
  has_running: boolean;
  is_pinned?: boolean;
  is_archived?: boolean;
  archived_sessions_count?: number;
  source?: 'recent' | 'session' | 'current' | 'metadata';
  sessions: SessionHistoryItem[];
}

export interface SessionHistoryResponse {
  current_project_path: string | null;
  projects: SessionHistoryProject[];
  standalone_sessions: SessionHistoryItem[];
}

export interface SkillPreferences {
  personal: Record<string, boolean>;
  coding: Record<string, boolean>;
}

export interface SkillCatalogItem {
  id: string;
  name: string;
  description: string;
  source: 'superpowers' | 'personal' | 'mcp' | 'a2a' | string;
  enabledByAgent: Record<AgentType, boolean>;
  recommendedFor: AgentType[];
  category: string;
  trustLevel: 'local' | 'trusted' | 'external' | string;
  status?: 'draft' | 'published' | 'archived' | string;
  scopes?: AgentType[];
  version?: string;
  validation?: SkillValidationSummary;
}

export interface SkillValidationIssue {
  level: 'error' | 'warning' | 'risk' | string;
  code: string;
  message: string;
}

export interface SkillValidationSummary {
  passed?: boolean;
  issues?: SkillValidationIssue[];
  warnings?: SkillValidationIssue[];
  risks?: SkillValidationIssue[];
  name?: string;
  description?: string;
}

export interface SkillDraftItem {
  id: string;
  draft_id: string;
  skill_id: string;
  name: string;
  description: string;
  status: 'draft' | string;
  source: string;
  scopes: AgentType[];
  enabledByAgent: Record<AgentType, boolean>;
  path: string;
  created_at?: string;
  updated_at?: string;
  validation?: SkillValidationSummary;
}

export interface SkillPreset {
  id: string;
  name: string;
  description: string;
  agentTypes: AgentType[];
  skillIds: string[];
}

export interface MatchedSkillTrace {
  id: string;
  name: string;
  category: string;
  source: string;
  reason: string;
}

export interface SkillCatalogResponse {
  skills: SkillCatalogItem[];
  preferences: SkillPreferences;
  defaults: SkillPreferences;
  presets: SkillPreset[];
  ignored?: string[];
}

export interface AgentInfo {
  type: AgentType;
  name: string;
  description: string;
  profile?: AgentProfile;
}

export interface AgentProfile {
  agent_type: AgentType;
  display_name: string;
  type_label: string;
  avatar_emoji?: string;
  subtitle?: string;
  updated_at?: string;
  source?: string;
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

export interface ErrorData {
  category: string;       // ErrorCategory: auth, network, rate_limit, provider, timeout, context_length, sandbox, tool_failure, tool_not_found, validation, not_found, internal, unknown
  message: string;
  retryable: boolean;
  details?: Record<string, any>;
}

export interface WS_EVENT {
  type: 'content' | 'reasoning' | 'knowledge_context' | 'tool_call' | 'image' | 'file_edit' | 'status' | 'error' | 'done' | 'cleared' | 'context_reset' | 'interrupted' | 'tool_result' | 'history_snapshot' | 'worker_start' | 'worker_content' | 'worker_tool_call' | 'worker_done' | 'plan_status' | 'plan_draft' | 'plan_questions' | 'plan_approved_waiting_build' | 'build_started' | 'build_paused' | 'build_ended' | 'plan_rejected' | 'plan_file_ready' | 'todo_update' | 'task_guidance_queued' | 'task_guidance_applied' | 'task_guidance_consumed' | 'task_guidance_stale' | 'task_guidance_deleted' | 'task_guidance_cleared' | 'run_created' | 'context_pack' | 'skills_matched' | 'skill_draft_ready' | 'guardrail_decision' | 'approval_required' | 'verification_start' | 'verification_result' | 'review_finding' | 'collaboration_run_created' | 'collaboration_task_update' | 'agent_message' | 'artifact_ready' | 'decision_required' | 'collaboration_run_completed' | 'run_completed' | 'automation_snapshot' | 'automation_action' | 'automation_trace' | 'automation_replay_status' | 'chat_mode' | 'thinking_intensity' | 'compacted' | 'rewound' | 'context_usage' | 'model_switched' | 'agent_switched' | 'suggest_agent_switch';
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

export interface ConnectorInfo {
  name: string;
  display_name: string;
  description: string;
  status: 'stopped' | 'running' | 'error';
  status_message: string;
  enabled: boolean;
  uptime_seconds: number;
  config: Record<string, any>;
  config_schema: Record<string, any>;
}
