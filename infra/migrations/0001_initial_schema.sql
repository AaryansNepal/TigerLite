-- TigerLite v2 — initial schema (covers all phases 0-4).
--
-- Apply with:   bash scripts/apply-migrations.sh
-- Or paste into the Supabase SQL editor as a single transaction.
--
-- Conventions:
--   - Every business table has tenant_id UUID NOT NULL.
--   - Every business table has RLS enabled and a tenant-isolation policy.
--   - Soft state (status fields) uses CHECK constraints instead of enums so
--     migrations are easy.

BEGIN;

-- pgcrypto for gen_random_uuid().
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- Tenancy
-- ============================================================

CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  ingest_token_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, tenant_id)
);

-- ============================================================
-- Connections (OTel ingest, GitHub, Slack)
-- ============================================================

CREATE TABLE IF NOT EXISTS connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('otel', 'github', 'slack')),
  status TEXT NOT NULL CHECK (status IN ('pending', 'connected', 'failed', 'revoked')),
  display_name TEXT,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  credentials_encrypted BYTEA,
  detected_services TEXT[],
  last_event_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS connections_tenant_kind_idx
  ON connections (tenant_id, kind);
-- Unique on (tenant, kind, display_name). NULL display_name is allowed
-- (multiple rows with NULL coexist) but we always populate display_name in
-- code, so ON CONFLICT (tenant_id, kind, display_name) works directly.
CREATE UNIQUE INDEX IF NOT EXISTS connections_tenant_kind_display_idx
  ON connections (tenant_id, kind, display_name);

-- ============================================================
-- Agents
-- ============================================================

CREATE TABLE IF NOT EXISTS agents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  objective TEXT NOT NULL,
  description TEXT NOT NULL,
  plan TEXT NOT NULL,
  scope_config JSONB NOT NULL,

  -- Triggers
  schedule_cron TEXT,
  anomaly_enabled BOOLEAN NOT NULL DEFAULT TRUE,

  -- Notifications
  slack_connection_id UUID REFERENCES connections(id),
  slack_channel TEXT,

  -- Code context
  github_connection_id UUID REFERENCES connections(id),
  github_repo TEXT,

  -- Memory (Phase 3)
  memory_ref TEXT,

  -- State
  status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'archived')) DEFAULT 'active',
  current_issue_id UUID,                -- forward-decl, FK added later in this file

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agents_tenant_status_idx ON agents (tenant_id, status);

-- ============================================================
-- Sessions (one investigation episode per session)
-- ============================================================

CREATE TABLE IF NOT EXISTS sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('investigation', 'verification', 'manual')),
  status TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed', 'timed_out')),
  trigger_kind TEXT NOT NULL,
  trigger_payload JSONB NOT NULL,

  root_snapshot_id TEXT NOT NULL,
  latest_snapshot_id TEXT,
  step_count INT NOT NULL DEFAULT 0,

  slack_thread_ts TEXT,

  outcome TEXT CHECK (outcome IN ('issue_found', 'no_issues', 'inconclusive', 'error')),
  finding_summary TEXT,

  started_at TIMESTAMPTZ DEFAULT now(),
  ended_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS sessions_agent_started_idx
  ON sessions (agent_id, started_at DESC);
CREATE INDEX IF NOT EXISTS sessions_tenant_status_idx
  ON sessions (tenant_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS sessions_slack_thread_idx
  ON sessions (slack_thread_ts) WHERE slack_thread_ts IS NOT NULL;

-- ============================================================
-- Findings (per-session structured output)
-- ============================================================

CREATE TABLE IF NOT EXISTS findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,

  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  evidence JSONB NOT NULL,
  suggested_action TEXT,
  signature TEXT NOT NULL,

  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS findings_agent_signature_idx
  ON findings (agent_id, signature);
CREATE INDEX IF NOT EXISTS findings_session_idx ON findings (session_id);

-- ============================================================
-- Issues (persistent open problems, Phase 3)
-- ============================================================

CREATE TABLE IF NOT EXISTS issues (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL
    CHECK (status IN ('open', 'verifying', 'resolved', 'regressed'))
    DEFAULT 'open',

  opened_by_session_id UUID NOT NULL REFERENCES sessions(id),
  resolved_by_session_id UUID REFERENCES sessions(id),

  next_verification_at TIMESTAMPTZ,
  verification_attempts INT NOT NULL DEFAULT 0,

  slack_thread_ts TEXT,
  slack_channel TEXT,

  signature TEXT NOT NULL,

  opened_at TIMESTAMPTZ DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS issues_tenant_status_idx ON issues (tenant_id, status);
CREATE INDEX IF NOT EXISTS issues_agent_status_idx  ON issues (agent_id, status);
CREATE INDEX IF NOT EXISTS issues_next_verify_idx
  ON issues (next_verification_at) WHERE status = 'verifying';

-- backfill the agents.current_issue_id forward reference
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'agents_current_issue_fk'
  ) THEN
    ALTER TABLE agents
      ADD CONSTRAINT agents_current_issue_fk
      FOREIGN KEY (current_issue_id) REFERENCES issues(id) ON DELETE SET NULL;
  END IF;
END$$;

-- ============================================================
-- Job queue (Postgres-as-queue)
-- ============================================================

CREATE TABLE IF NOT EXISTS jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  kind TEXT NOT NULL,                -- anomaly | cron | slack_message | snapshot_ready | verify_issue
  payload JSONB NOT NULL,

  visible_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  consumer_id TEXT,
  locked_at TIMESTAMPTZ,
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  last_error TEXT,

  created_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS jobs_visible_consumer_idx
  ON jobs (visible_at, consumer_id) WHERE completed_at IS NULL;
CREATE INDEX IF NOT EXISTS jobs_locked_idx
  ON jobs (locked_at) WHERE consumer_id IS NOT NULL AND completed_at IS NULL;

-- ============================================================
-- updated_at triggers
-- ============================================================

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS agents_updated_at ON agents;
CREATE TRIGGER agents_updated_at
  BEFORE UPDATE ON agents
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS connections_updated_at ON connections;
CREATE TRIGGER connections_updated_at
  BEFORE UPDATE ON connections
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================
-- RLS — every business table is tenant-isolated.
-- ============================================================

-- Helper: which tenants does the current authenticated user belong to?
CREATE OR REPLACE FUNCTION current_user_tenants() RETURNS SETOF UUID
LANGUAGE SQL STABLE AS $$
  SELECT tenant_id FROM memberships WHERE user_id = auth.uid();
$$;

-- enable RLS
ALTER TABLE tenants     ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents      ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE findings    ENABLE ROW LEVEL SECURITY;
ALTER TABLE issues      ENABLE ROW LEVEL SECURITY;
-- jobs and tenants intentionally NOT exposed to client roles via PostgREST;
-- service_role bypasses RLS.

-- policy: SELECT/INSERT/UPDATE/DELETE only own tenants
DROP POLICY IF EXISTS tenants_membership ON tenants;
CREATE POLICY tenants_membership ON tenants
  FOR ALL
  USING (id IN (SELECT current_user_tenants()))
  WITH CHECK (id IN (SELECT current_user_tenants()));

DROP POLICY IF EXISTS memberships_self ON memberships;
CREATE POLICY memberships_self ON memberships
  FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS connections_tenant ON connections;
CREATE POLICY connections_tenant ON connections
  FOR ALL
  USING (tenant_id IN (SELECT current_user_tenants()))
  WITH CHECK (tenant_id IN (SELECT current_user_tenants()));

DROP POLICY IF EXISTS agents_tenant ON agents;
CREATE POLICY agents_tenant ON agents
  FOR ALL
  USING (tenant_id IN (SELECT current_user_tenants()))
  WITH CHECK (tenant_id IN (SELECT current_user_tenants()));

DROP POLICY IF EXISTS sessions_tenant ON sessions;
CREATE POLICY sessions_tenant ON sessions
  FOR ALL
  USING (tenant_id IN (SELECT current_user_tenants()))
  WITH CHECK (tenant_id IN (SELECT current_user_tenants()));

DROP POLICY IF EXISTS findings_tenant ON findings;
CREATE POLICY findings_tenant ON findings
  FOR ALL
  USING (tenant_id IN (SELECT current_user_tenants()))
  WITH CHECK (tenant_id IN (SELECT current_user_tenants()));

DROP POLICY IF EXISTS issues_tenant ON issues;
CREATE POLICY issues_tenant ON issues
  FOR ALL
  USING (tenant_id IN (SELECT current_user_tenants()))
  WITH CHECK (tenant_id IN (SELECT current_user_tenants()));

-- ============================================================
-- Convenience views
-- ============================================================

-- Per-tenant open issue count (used for the sidebar badge).
CREATE OR REPLACE VIEW tenant_open_issue_count AS
SELECT
  tenant_id,
  COUNT(*) FILTER (WHERE status IN ('open', 'verifying', 'regressed')) AS open_count
FROM issues
GROUP BY tenant_id;

-- Latest session per agent (for the agent list summary).
CREATE OR REPLACE VIEW agent_latest_session AS
SELECT DISTINCT ON (agent_id)
  agent_id,
  id AS session_id,
  status,
  outcome,
  finding_summary,
  started_at,
  ended_at
FROM sessions
ORDER BY agent_id, started_at DESC;

COMMIT;
