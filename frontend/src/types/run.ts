/**
 * Authoritative TypeScript Type Definitions for Cloud-Native AI Coding Harness
 * Generated for Milestone 6 Frontend.
 */

export type RunStatus =
  | "QUEUED"
  | "PREPARING"
  | "RUNNING"
  | "PAUSED"
  | "SUCCEEDED"
  | "FAILED"
  | "TERMINATED";

export type VerificationMode = "required" | "none";

export interface RunOptions {
  verification?: VerificationMode;
  multi_agent?: boolean;
}

export interface Run {
  id: string;
  user_id: string;
  repo_url: string | null;
  task: string;
  status: RunStatus;
  options: RunOptions;
  is_pausing: boolean;
  baseline_sha: string | null;
  error_reason: string | null;
  created_at: string;
  updated_at: string;
}

export type PauseMode = "boundary" | "now";

export interface PauseRequest {
  mode?: PauseMode;
}

export interface GuidanceRequest {
  message: string;
}

export interface TerminateRequest {
  reason?: string;
}

export interface ControlResponse {
  action: string;
  changed: boolean;
}

export interface GuidanceResponse {
  status: string;
}

export interface ArtifactUrls {
  patch_url: string | null;
  logs_url: string | null;
  transcript_url: string | null;
}

export type DiffFileStatus = "modified" | "added" | "deleted" | "renamed" | "binary";

export interface FileDiff {
  path: string;
  status: DiffFileStatus;
  additions: number;
  deletions: number;
  old_content: string | null;
  new_content: string | null;
  diff_patch: string | null;
}

// -------------------------------------------------------------------------
// WebSocket and Event Stream Typings
// -------------------------------------------------------------------------

export type RunEventType =
  | "status_change"
  | "reasoning"
  | "plan"
  | "decision"
  | "tool_call"
  | "tool_result"
  | "terminal_output"
  | "truncation_marker"
  | "guidance"
  | "agent_status"
  | "agent_message";

export interface StatusChangePayload {
  status?: RunStatus;
  new_status?: RunStatus;
  old_status?: RunStatus;
  error_reason?: string | null;
  reason?: string | null;
  is_pausing?: boolean;
}

export interface ReasoningPayload {
  thought: string;
}

export interface PlanPayload {
  steps: string[] | string;
}

export interface DecisionPayload {
  decision: string;
}

export interface ToolCallPayload {
  id: string;
  name: "read_file" | "write_file" | "list_dir" | "run_command" | "finish" | string;
  arguments: Record<string, any>;
}

export interface ToolResultPayload {
  id: string;
  name: string;
  output: string;
  is_error: boolean;
  path?: string;
  command?: string;
  exit_code?: number;
  purpose?: "test" | "other" | string;
  summary?: string;
}

export interface TerminalOutputPayload {
  stream: "stdout" | "stderr";
  data: string;
}

export interface TruncationMarkerPayload {
  message: string;
  limit: number;
}

export interface GuidancePayload {
  message: string;
}

export interface BaseRunEvent<TType extends string, TPayload> {
  seq: number;
  ts: string;
  type: TType;
  payload: TPayload;
}

export type StatusChangeEvent = BaseRunEvent<"status_change", StatusChangePayload>;
export type ReasoningEvent = BaseRunEvent<"reasoning", ReasoningPayload>;
export type PlanEvent = BaseRunEvent<"plan", PlanPayload>;
export type DecisionEvent = BaseRunEvent<"decision", DecisionPayload>;
export type ToolCallEvent = BaseRunEvent<"tool_call", ToolCallPayload>;
export type ToolResultEvent = BaseRunEvent<"tool_result", ToolResultPayload>;
export type TerminalOutputEvent = BaseRunEvent<"terminal_output", TerminalOutputPayload>;
export type TruncationMarkerEvent = BaseRunEvent<"truncation_marker", TruncationMarkerPayload>;
export type GuidanceEvent = BaseRunEvent<"guidance", GuidancePayload>;

export type RunEvent =
  | StatusChangeEvent
  | ReasoningEvent
  | PlanEvent
  | DecisionEvent
  | ToolCallEvent
  | ToolResultEvent
  | TerminalOutputEvent
  | TruncationMarkerEvent
  | GuidanceEvent
  | BaseRunEvent<string, Record<string, any>>;

export interface ToolCallItem {
  id: string;
  name: string;
  arguments: Record<string, any>;
  status: "running" | "success" | "error";
  output?: string;
  exitCode?: number;
  purpose?: string;
  path?: string;
  command?: string;
  summary?: string;
  timestamp: string;
}

export interface TerminalChunk {
  stream: "stdout" | "stderr";
  data: string;
  seq: number;
}

export interface CreateRunJsonPayload {
  task: string;
  repo_url?: string | null;
  options?: RunOptions;
  archive?: string; // base64 string
}

export interface HealthResponse {
  status: string;
}

export interface ReadyResponse {
  status: "ready" | "not_ready";
  dependencies: {
    database: string;
    storage: string;
    docker_proxy: string;
    sandbox_image: string;
    [key: string]: string;
  };
}
