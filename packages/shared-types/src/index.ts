/**
 * Types shared between the Next.js dashboard and (eventually) typed API
 * clients elsewhere. These mirror Pydantic models in
 * services/control-plane/src/tigerlite_control/models.py.
 */

export type ConnectionKind = "otel" | "github" | "slack";
export type ConnectionStatus = "pending" | "connected" | "failed" | "revoked";

export interface Connection {
  id: string;
  tenant_id: string;
  kind: ConnectionKind;
  status: ConnectionStatus;
  display_name: string | null;
  config: Record<string, unknown>;
  detected_services: string[] | null;
  last_event_at: string | null;
  created_at: string;
  updated_at: string;
}

export type AgentStatus = "active" | "paused" | "archived";

export interface Agent {
  id: string;
  tenant_id: string;
  name: string;
  objective: string;
  description: string;
  plan: string;
  scope_config: Record<string, unknown>;
  schedule_cron: string | null;
  anomaly_enabled: boolean;
  slack_connection_id: string | null;
  slack_channel: string | null;
  github_connection_id: string | null;
  github_repo: string | null;
  memory_ref: string | null;
  status: AgentStatus;
  current_issue_id: string | null;
  created_at: string;
  updated_at: string;
}

export type SessionStatus = "running" | "done" | "failed" | "timed_out";
export type SessionKind = "investigation" | "verification" | "manual";
export type SessionOutcome = "issue_found" | "no_issues" | "inconclusive" | "error";

export interface Session {
  id: string;
  tenant_id: string;
  agent_id: string;
  kind: SessionKind;
  status: SessionStatus;
  trigger_kind: string;
  trigger_payload: Record<string, unknown>;
  root_snapshot_id: string;
  latest_snapshot_id: string | null;
  step_count: number;
  slack_thread_ts: string | null;
  outcome: SessionOutcome | null;
  finding_summary: string | null;
  started_at: string;
  ended_at: string | null;
}

export type Severity = "low" | "medium" | "high" | "critical";

export interface Finding {
  id: string;
  tenant_id: string;
  agent_id: string;
  session_id: string;
  title: string;
  summary: string;
  severity: Severity;
  evidence: Record<string, unknown>;
  suggested_action: string | null;
  signature: string;
  created_at: string;
}

export type IssueStatus = "open" | "verifying" | "resolved" | "regressed";

export interface Issue {
  id: string;
  tenant_id: string;
  agent_id: string;
  title: string;
  summary: string;
  severity: Severity;
  status: IssueStatus;
  opened_by_session_id: string;
  resolved_by_session_id: string | null;
  next_verification_at: string | null;
  verification_attempts: number;
  slack_thread_ts: string | null;
  slack_channel: string | null;
  signature: string;
  opened_at: string;
  resolved_at: string | null;
}

export type SnapshotObjectType =
  | "system_prompt"
  | "trigger_event"
  | "user_message"
  | "assistant_message"
  | "tool_call"
  | "tool_result"
  | "reasoning";

export interface SnapshotObject {
  type: SnapshotObjectType;
  version: number;
  content: Record<string, unknown> | string;
}
