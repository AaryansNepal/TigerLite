# Data model

Three storage systems hold three categories of data:

- **Postgres (Supabase)** — control plane: tenants, users, agents, sessions index, connections, issues, findings, jobs.
- **Iceberg on S3** — telemetry: OTLP-shaped traces, logs, metrics. Multi-tenant via leading partition.
- **S3 (separate bucket)** — agent runtime artifacts: snapshot manifests, content-addressed objects, tool result artifacts, agent memory.

## Postgres schema

All tables have `tenant_id UUID NOT NULL` (except `tenants` itself) with row-level security policies enforcing isolation. Use `gen_random_uuid()` for IDs.

```sql
-- ========================================
-- Tenancy & users
-- ========================================

CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,           -- URL-safe, e.g. "acme-corp"
  ingest_token_hash TEXT NOT NULL,     -- bcrypt hash of OTLP ingest token
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Users are managed by Supabase Auth (auth.users).
-- We just need a join table to tenants.

CREATE TABLE memberships (
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'member')),
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (user_id, tenant_id)
);

-- ========================================
-- Connections (OTel ingest, GitHub, Slack)
-- ========================================

CREATE TABLE connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('otel', 'github', 'slack')),
  status TEXT NOT NULL CHECK (status IN ('pending', 'connected', 'failed', 'revoked')),
  display_name TEXT,                   -- e.g. "AaryansNepal/opentelemetry-demo" for github
  config JSONB NOT NULL DEFAULT '{}',  -- non-secret config (channel_id, repo_owner, etc.)
  credentials_encrypted BYTEA,         -- encrypted OAuth tokens, GitHub install token, etc.
  detected_services TEXT[],            -- for otel: list of service.name values seen
  last_event_at TIMESTAMPTZ,           -- for otel: last time we received an event
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (tenant_id, kind, display_name)
);

CREATE INDEX ON connections (tenant_id, kind);

-- ========================================
-- Agents
-- ========================================

CREATE TABLE agents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,                  -- "Checkout flow monitor"
  objective TEXT NOT NULL,             -- one-line plain language: "checkout flow should always be fast"
  description TEXT NOT NULL,           -- generated from compiler: "Monitors /checkout and /payment for errors and slow downs."
  plan TEXT NOT NULL,                  -- editable freeform runbook (the "Plan" field in UI)
  scope_config JSONB NOT NULL,         -- compiled config: {services: [...], endpoints: [...], thresholds: {...}}
  
  -- Triggers
  schedule_cron TEXT,                  -- e.g. "0 * * * *" for hourly; null if no schedule
  anomaly_enabled BOOLEAN DEFAULT TRUE,
  
  -- Notifications
  slack_connection_id UUID REFERENCES connections(id),
  slack_channel TEXT,
  
  -- Code context
  github_connection_id UUID REFERENCES connections(id),
  github_repo TEXT,                    -- "owner/repo"
  
  -- Memory
  memory_ref TEXT,                     -- S3 key: "agents/{id}/memory/{hash}.json"
  
  -- State
  status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'archived')) DEFAULT 'active',
  current_issue_id UUID,               -- forward-decl, see issues table
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON agents (tenant_id, status);

-- ========================================
-- Sessions (investigation episodes)
-- ========================================

CREATE TABLE sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('investigation', 'verification', 'manual')),
  status TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed', 'timed_out')),
  trigger_kind TEXT NOT NULL,          -- 'anomaly', 'cron', 'slack', 'manual'
  trigger_payload JSONB NOT NULL,
  
  root_snapshot_id TEXT NOT NULL,      -- S3 key of snapshot 0
  latest_snapshot_id TEXT,             -- S3 key of most recent snapshot
  step_count INT DEFAULT 0,
  
  -- For Slack-driven sessions
  slack_thread_ts TEXT,
  
  -- Outcome
  outcome TEXT CHECK (outcome IN ('issue_found', 'no_issues', 'inconclusive', 'error')),
  finding_summary TEXT,
  
  started_at TIMESTAMPTZ DEFAULT now(),
  ended_at TIMESTAMPTZ
);

CREATE INDEX ON sessions (agent_id, started_at DESC);
CREATE INDEX ON sessions (tenant_id, status);
CREATE UNIQUE INDEX ON sessions (slack_thread_ts) WHERE slack_thread_ts IS NOT NULL;

-- ========================================
-- Findings (per-session structured output)
-- ========================================

CREATE TABLE findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  evidence JSONB NOT NULL,             -- { "affected_count": 1247, "customers": 892, "first_seen": "...", "commit": "abc123", ... }
  suggested_action TEXT,
  signature TEXT NOT NULL,             -- short hash of the finding for deduplication
  
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON findings (agent_id, signature);
CREATE INDEX ON findings (session_id);

-- ========================================
-- Issues (persistent open problems)
-- ========================================
-- An issue is "the agent has noticed something wrong and is tracking it
-- across multiple sessions" (initial investigation, then verification, then
-- possible regression detection).

CREATE TABLE issues (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open', 'verifying', 'resolved', 'regressed')) DEFAULT 'open',
  
  opened_by_session_id UUID NOT NULL REFERENCES sessions(id),
  resolved_by_session_id UUID REFERENCES sessions(id),
  
  -- For verification scheduling
  next_verification_at TIMESTAMPTZ,
  verification_attempts INT DEFAULT 0,
  
  -- For Slack threading
  slack_thread_ts TEXT,                -- continuation thread for all related messages
  slack_channel TEXT,
  
  signature TEXT NOT NULL,             -- for dedup against repeat detections
  
  opened_at TIMESTAMPTZ DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

CREATE INDEX ON issues (tenant_id, status);
CREATE INDEX ON issues (agent_id, status);
CREATE INDEX ON issues (next_verification_at) WHERE status = 'verifying';

-- Backfill the agents.current_issue_id forward reference
ALTER TABLE agents ADD CONSTRAINT agents_current_issue_fk
  FOREIGN KEY (current_issue_id) REFERENCES issues(id) ON DELETE SET NULL;

-- ========================================
-- Job queue
-- ========================================

CREATE TABLE jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,             -- not FK'd — we want to enqueue before validating
  kind TEXT NOT NULL,                  -- 'anomaly', 'cron', 'slack_message', 'snapshot_ready', 'verify_issue'
  payload JSONB NOT NULL,
  
  visible_at TIMESTAMPTZ DEFAULT now(),
  consumer_id TEXT,
  locked_at TIMESTAMPTZ,
  attempts INT DEFAULT 0,
  max_attempts INT DEFAULT 3,
  
  created_at TIMESTAMPTZ DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX ON jobs (visible_at, consumer_id) WHERE completed_at IS NULL;
CREATE INDEX ON jobs (locked_at) WHERE consumer_id IS NOT NULL AND completed_at IS NULL;

-- ========================================
-- Row-level security policies (sample)
-- ========================================

-- Enable RLS on all tenant-scoped tables
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE connections ENABLE ROW LEVEL SECURITY;

-- Helper: get the current user's tenant memberships
CREATE OR REPLACE FUNCTION current_user_tenants() RETURNS SETOF UUID AS $$
  SELECT tenant_id FROM memberships WHERE user_id = auth.uid();
$$ LANGUAGE SQL STABLE;

-- Sample policy: users can only see/modify their own tenant's agents
CREATE POLICY agents_tenant_isolation ON agents
  USING (tenant_id IN (SELECT current_user_tenants()));

-- Repeat similar policies for sessions, findings, issues, connections.

-- ========================================
-- Triggers for updated_at
-- ========================================

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER agents_updated_at BEFORE UPDATE ON agents
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

## Iceberg tables (telemetry)

Three tables, one per OTel signal type. All tables are partitioned by `(tenant_id, day)` so DuckDB scans only relevant partitions.

```sql
-- traces table
CREATE TABLE traces (
  tenant_id STRING NOT NULL,
  trace_id STRING NOT NULL,
  span_id STRING NOT NULL,
  parent_span_id STRING,
  trace_state STRING,
  
  -- Timing
  start_time TIMESTAMP NOT NULL,
  end_time TIMESTAMP NOT NULL,
  duration_ms DOUBLE,
  
  -- Identity
  service_name STRING,
  service_version STRING,
  scope_name STRING,
  scope_version STRING,
  span_name STRING,
  span_kind STRING,                    -- INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER
  
  -- Status
  status_code STRING,                  -- OK, ERROR, UNSET
  status_message STRING,
  
  -- Attributes (preserved as map for flexibility)
  attributes MAP<STRING, STRING>,
  resource_attributes MAP<STRING, STRING>,
  
  -- Common attributes promoted to columns for efficient querying
  http_method STRING,
  http_route STRING,
  http_status_code INT,
  http_url STRING,
  rpc_method STRING,
  rpc_service STRING,
  db_system STRING,
  db_statement STRING,
  
  -- Events and links serialized as JSON
  events STRING,                       -- JSON array of {time, name, attributes}
  links STRING,                        -- JSON array of links
  
  ingested_at TIMESTAMP NOT NULL,
  day DATE NOT NULL                    -- partition column
)
USING iceberg
PARTITIONED BY (tenant_id, day)
TBLPROPERTIES (
  'write.target-file-size-bytes' = '134217728'  -- 128 MB
);

-- logs table
CREATE TABLE logs (
  tenant_id STRING NOT NULL,
  trace_id STRING,
  span_id STRING,
  
  time TIMESTAMP NOT NULL,
  observed_time TIMESTAMP,
  
  severity_text STRING,                -- TRACE, DEBUG, INFO, WARN, ERROR, FATAL
  severity_number INT,
  
  service_name STRING,
  scope_name STRING,
  
  body STRING,                         -- the log message text
  body_type STRING,                    -- 'string', 'json', 'kvlist'
  
  attributes MAP<STRING, STRING>,
  resource_attributes MAP<STRING, STRING>,
  
  ingested_at TIMESTAMP NOT NULL,
  day DATE NOT NULL
)
USING iceberg
PARTITIONED BY (tenant_id, day);

-- metrics table
CREATE TABLE metrics (
  tenant_id STRING NOT NULL,
  
  metric_name STRING NOT NULL,
  metric_type STRING NOT NULL,         -- 'gauge', 'sum', 'histogram', 'summary'
  metric_unit STRING,
  metric_description STRING,
  
  service_name STRING,
  scope_name STRING,
  
  time TIMESTAMP NOT NULL,
  start_time TIMESTAMP,
  
  -- Value (one of these will be set based on metric_type)
  gauge_value DOUBLE,
  sum_value DOUBLE,
  sum_is_monotonic BOOLEAN,
  histogram_count BIGINT,
  histogram_sum DOUBLE,
  histogram_buckets STRING,            -- JSON: [{bound, count}, ...]
  
  attributes MAP<STRING, STRING>,
  resource_attributes MAP<STRING, STRING>,
  
  ingested_at TIMESTAMP NOT NULL,
  day DATE NOT NULL
)
USING iceberg
PARTITIONED BY (tenant_id, day);
```

### Tenant scoping enforcement

Every DuckDB query goes through a wrapper that prepends a tenant filter. Never let the LLM bypass this — any tool call ultimately resolves to:

```python
def enforce_tenant_filter(sql: str, tenant_id: str) -> str:
    # Use DuckDB's CTE pattern to scope every table reference
    # WITH traces AS (SELECT * FROM iceberg_scan('traces') WHERE tenant_id = '<id>'),
    #      logs AS (SELECT * FROM iceberg_scan('logs') WHERE tenant_id = '<id>'),
    #      metrics AS (SELECT * FROM iceberg_scan('metrics') WHERE tenant_id = '<id>')
    # <user query>
    
    return f"""
    WITH 
      traces AS (SELECT * FROM iceberg_scan('s3://tigerlite-telemetry/traces/') WHERE tenant_id = $1),
      logs AS (SELECT * FROM iceberg_scan('s3://tigerlite-telemetry/logs/') WHERE tenant_id = $1),
      metrics AS (SELECT * FROM iceberg_scan('s3://tigerlite-telemetry/metrics/') WHERE tenant_id = $1)
    {sql}
    """
```

Use parameterized queries. The agent's SQL goes after the CTE, so it can only reference the scoped views, never the raw tables.

## S3 layout

Two buckets, deliberately separated:

### `tigerlite-{stage}-telemetry`
Iceberg-managed. Don't write to this directly except via Iceberg APIs.

```
tigerlite-{stage}-telemetry/
├── traces/
│   ├── metadata/         # Iceberg catalog metadata
│   └── data/             # Parquet files
├── logs/
└── metrics/
```

### `tigerlite-{stage}-snapshots`
Application-managed. Content-addressable.

```
tigerlite-{stage}-snapshots/
├── objects/                                    # Content-addressed objects
│   └── {sha256[0:2]}/{sha256}                  # e.g. objects/ab/abcdef...
├── snapshots/                                  # Snapshot manifests
│   └── {tenant_id}/{agent_id}/{session_id}/
│       └── {version:08d}.json                  # snapshots/abc/def/ghi/00000003.json
├── artifacts/                                  # Large tool results
│   └── {sha256[0:2]}/{sha256}.{ext}
└── agents/                                     # Per-agent memory
    └── {agent_id}/memory/{hash}.json
```

Object format:

```json
{
  "type": "tool_call",
  "version": 1,
  "content": {
    "id": "call_abc123",
    "name": "query_telemetry",
    "args": {"sql": "SELECT ..."}
  }
}
```

Snapshot manifest format:

```json
{
  "tenant_id": "...",
  "agent_id": "...",
  "session_id": "...",
  "version": 3,
  "object_hashes": ["a1b2...", "c3d4...", "e5f6...", "g7h8..."],
  "created_at": "2026-04-27T16:34:12Z",
  "parent_snapshot_id": "snapshots/.../00000002.json"
}
```

Atomic write: PUT with `If-None-Match: *` header. Fails with 412 if another writer already created the same version. Loser reads new state and decides whether to retry or abort.

## Indexes and lookups

The most expensive queries to plan for:

- "Show all agents for this tenant" → covered by `agents (tenant_id, status)`.
- "List recent sessions for this agent" → covered by `sessions (agent_id, started_at DESC)`.
- "Find session by Slack thread" → covered by unique partial index on `slack_thread_ts`.
- "Open issues count for sidebar badge" → covered by `issues (tenant_id, status)`.
- "Next verification to run" → covered by partial index on `next_verification_at`.
- "Pending jobs to consume" → covered by `jobs (visible_at, consumer_id)` partial index.

Don't pre-optimize beyond these. Postgres handles the rest at demo scale.
