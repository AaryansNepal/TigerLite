"""Pydantic models for the control plane API.

These mirror the Postgres schema. Two layers: input (request body) and
output (response body). Output models always include id + timestamps.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ----------------------------------------------------------
# Connections
# ----------------------------------------------------------

ConnectionKind = Literal["otel", "github", "slack"]
ConnectionStatus = Literal["pending", "connected", "failed", "revoked"]


class Connection(BaseModel):
    id: UUID
    tenant_id: UUID
    kind: ConnectionKind
    status: ConnectionStatus
    display_name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    detected_services: list[str] | None = None
    last_event_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------
# Agents
# ----------------------------------------------------------

AgentStatus = Literal["active", "paused", "archived"]


class AgentConfig(BaseModel):
    """The compiler's structured output. Stored on the agent row."""
    name: str
    objective: str
    description: str
    plan: str
    scope_config: dict[str, Any]
    schedule_cron: str | None = None
    anomaly_enabled: bool = True
    slack_channel: str | None = None
    github_repo: str | None = None


class AgentCreateRequest(BaseModel):
    """User submits the natural-language objective; we run the compiler and
    persist the result. The compiler may return clarifying questions, in
    which case the dashboard sends back another request with `answers`.

    The compiler frequently emits option values as JSON numbers (e.g. 500 for
    an ms threshold), so we accept a permissive value type and stringify
    on the backend before passing to the LLM.

    `transcript` is the running conversation thread (user typed prompts +
    agent's clarifying questions and replies). The dashboard sends the full
    thread on the *final* create call so we persist it on the agent row.
    """
    objective: str
    answers: dict[str, str | int | float | bool] | None = None
    transcript: list[dict[str, Any]] | None = None
    slack_connection_id: UUID | None = None
    github_connection_id: UUID | None = None

    def normalised_answers(self) -> dict[str, str]:
        if not self.answers:
            return {}
        return {k: str(v) for k, v in self.answers.items()}


class Agent(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    objective: str
    description: str
    plan: str
    scope_config: dict[str, Any]
    schedule_cron: str | None = None
    anomaly_enabled: bool
    slack_connection_id: UUID | None = None
    slack_channel: str | None = None
    github_connection_id: UUID | None = None
    github_repo: str | None = None
    memory_ref: str | None = None
    chat_transcript: list[dict[str, Any]] = Field(default_factory=list)
    status: AgentStatus
    current_issue_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class AgentPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    plan: str | None = None
    scope_config: dict[str, Any] | None = None
    schedule_cron: str | None = None
    anomaly_enabled: bool | None = None
    slack_channel: str | None = None
    github_repo: str | None = None
    status: AgentStatus | None = None


# ----------------------------------------------------------
# Sessions
# ----------------------------------------------------------

SessionStatus = Literal["running", "done", "failed", "timed_out"]
SessionKind = Literal["investigation", "verification", "manual"]
SessionOutcome = Literal["issue_found", "no_issues", "inconclusive", "error"]


class Session(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: UUID
    kind: SessionKind
    status: SessionStatus
    trigger_kind: str
    trigger_payload: dict[str, Any]
    root_snapshot_id: str
    latest_snapshot_id: str | None = None
    step_count: int
    slack_thread_ts: str | None = None
    outcome: SessionOutcome | None = None
    finding_summary: str | None = None
    started_at: datetime
    ended_at: datetime | None = None


# ----------------------------------------------------------
# Findings
# ----------------------------------------------------------

Severity = Literal["low", "medium", "high", "critical"]


class Finding(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: UUID
    session_id: UUID
    title: str
    summary: str
    severity: Severity
    evidence: dict[str, Any]
    suggested_action: str | None = None
    signature: str
    created_at: datetime


# ----------------------------------------------------------
# Issues
# ----------------------------------------------------------

IssueStatus = Literal["open", "verifying", "resolved", "regressed"]


class Issue(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: UUID
    title: str
    summary: str
    severity: Severity
    status: IssueStatus
    opened_by_session_id: UUID
    resolved_by_session_id: UUID | None = None
    next_verification_at: datetime | None = None
    verification_attempts: int
    slack_thread_ts: str | None = None
    slack_channel: str | None = None
    signature: str
    opened_at: datetime
    resolved_at: datetime | None = None


# ----------------------------------------------------------
# Manual triggers
# ----------------------------------------------------------

class ManualTriggerRequest(BaseModel):
    reason: str | None = "manual_run"
