# Architecture

## Three planes

TigerLite is structured into three logical planes that map cleanly onto separate operational responsibilities. The architecture deliberately mirrors Firetiger's published architecture — Iceberg + DuckDB data lake, snapshot-based agents, MCP-based tool extensibility — adapted to a demo-scale budget.

```
                  ┌────────────────────────────────────────────────────┐
                  │                    DATA PLANE                       │
                  │                                                     │
   Monitored ────▶│   OTLP receiver (Go) ──▶ Iceberg on S3              │
   app (OTel)     │                              ▲                      │
                  │                              │ DuckDB queries       │
                  └──────────────────────────────┼──────────────────────┘
                                                 │
                  ┌──────────────────────────────┼──────────────────────┐
                  │                  TRIGGER PLANE                       │
                  │                              │                       │
   Anomaly ──┐    │   Trigger router ────▶ Snapshot N (S3)               │
   Cron ─────┤───▶│                                                      │
   Slack ────┘    │                                                      │
                  └──────────────────────────────┼──────────────────────┘
                                                 │
                  ┌──────────────────────────────┼──────────────────────┐
                  │                AGENT RUNTIME PLANE                   │
                  │                              ▼                       │
                  │       Worker reads ──▶ Gemini ──▶ Tool exec          │
                  │            ▲                          │              │
                  │            │                          ▼              │
                  │            └────────── Snapshot N+1 (S3) ─┐          │
                  │                                            │         │
                  │             (loops until terminal) ◀──────┘          │
                  │                                                       │
                  │   Tools: query_telemetry, read_artifact,              │
                  │          GitHub MCP, Slack MCP, record_finding        │
                  └───────────────────────────────────────────────────────┘
```

### Data plane

Telemetry intake and storage. Customers point any OpenTelemetry SDK at our OTLP endpoint with their per-tenant ingest token. The Go ingestion service authenticates the token, batches incoming traces/logs/metrics, and writes them to tenant-scoped Apache Iceberg tables on S3. DuckDB queries Iceberg in-process from the agent runtime and the watcher — no separate query engine to operate.

### Trigger plane

Three sources, one queue. **Anomaly watcher** (Python, runs every 60s) compares current vs baseline metrics for each active agent and fires when deviation crosses threshold. **Cron** fires per-agent on user-configured schedules and for verification sessions. **Slack webhook** fires when the user mentions an agent or replies in a connected thread.

The **trigger router** consumes the queue, looks up the relevant agent, decides new-or-resume-session, and writes the initial snapshot for the runtime to pick up.

### Agent runtime plane

The snapshot loop. A long-running Python worker consumes pending-snapshot jobs from the queue, reads the snapshot from S3, replays its objects into a Gemini conversation, calls Gemini with available tools, executes whatever tool Gemini wants, composes new objects (assistant message, tool call, tool result), and writes a new snapshot. The new snapshot is itself a new job — the loop self-recurses through the queue until the LLM signals terminal state.

Same loop, different driver: in production this could be `lambda_handler.py` triggered by S3 event notifications instead of `worker.py` consuming a queue. The pure-function `run_one_step(snapshot_id) → next_snapshot_id` is unchanged.

See `AGENT_DESIGN.md` for the runtime in detail.

## Data flow — happy path

A complete trace of the demo path, end to end:

1. The forked Astronomy Shop is running. Its OTel collector exports to TigerLite's OTLP endpoint with the user's ingest token.
2. Traces land in Iceberg tables under `tenant_id = X`, partitioned by `(tenant_id, day)`.
3. Anomaly watcher's per-minute tick runs the agent's scope query against DuckDB. P95 on `/checkout` jumped from 240ms to 2400ms in the last 5 minutes vs the 7-day baseline.
4. Watcher pushes `{kind: "anomaly", agent_id, evidence: {...}}` to the queue.
5. Trigger router picks it up. Agent has no open session for this issue type, so router creates a new session, writes initial snapshot containing system prompt + agent's compiled plan + the anomaly event description.
6. Initial snapshot write enqueues `{kind: "snapshot_ready", snapshot_id: ...}`.
7. Agent runtime worker picks up the job. Replays snapshot objects into Gemini's message format. Calls Gemini with available tools.
8. Gemini calls `query_telemetry(sql)` to inspect error patterns. Worker executes against DuckDB, gets back rows. Result over 5000 tokens — full result saved to S3 as artifact `<sha>`, agent receives `{rows: 5, columns: [...], artifact_id: <sha>}`.
9. New snapshot written with assistant message + tool_call + tool_result objects. Self-enqueues.
10. Next worker invocation. Gemini analyzes, calls `read_artifact(<sha>, jq=".[0:10]")` to see specific rows.
11. Several iterations of `query_telemetry` + `read_artifact`, narrowing on a payment-service spike correlating with deploys.
12. Gemini calls `list_recent_commits(repo, since="1h ago")` via the GitHub MCP. Identifies a likely culprit commit.
13. Gemini calls `get_commit_diff(repo, sha)`. Reads the diff.
14. Gemini calls `record_finding(...)` with title, summary, root cause, evidence.
15. Gemini calls `post_to_slack(channel, blocks)` with structured message.
16. Gemini returns terminal — investigation complete.
17. Worker marks session done. Issue created. Verification session scheduled for 10 minutes from now.

End to end: ~60 seconds in the demo path, dominated by Gemini latency. Roughly 6–10 worker iterations per investigation.

## Hosting topology

For the demo phase, total cost is $0/month within free tiers.

| Component | Where | Why |
|-----------|-------|-----|
| Dashboard (Next.js) | Vercel free | Best-in-class Next.js host, free SSL, GitHub-integrated deploys |
| Next.js API routes (auth callbacks, slack events, agent CRUD) | Vercel | Co-located with frontend |
| FastAPI control plane (heavy logic, LLM calls, DuckDB) | Fly.io free shared-cpu-1x | Long-running, needs persistent connections |
| OTLP receiver (Go) | Fly.io | Same VM as control plane, persistent process |
| Iceberg REST catalog (`tabulario/iceberg-rest`) | Fly.io | Same VM |
| Agent runtime worker (Python) | Fly.io | Same VM (or scale separately if needed) |
| Telemetry storage | AWS S3 free tier (5 GB) | Cheap, durable, native Iceberg target |
| Snapshot + object + artifact storage | AWS S3 free tier (separate bucket) | Same reasons |
| Postgres + Auth + Realtime | Supabase free tier | Auth + DB + realtime in one |
| Astronomy Shop (monitored app) | User's laptop during demo, or DigitalOcean droplet for "live" | Microservices, won't run on Vercel |

12-month free tier risk: AWS S3 free tier expires after 12 months. Plan accordingly or migrate to a paid tier (~$5/month at demo scale) before the cliff.

## Why this design — the three properties that matter

**Crash consistency.** LLM calls take 5–30 seconds. Tool calls (especially DuckDB scans) can take longer. Across a multi-step investigation, the chance of *something* failing is high. Snapshot-based agents lose at most one step on failure — the next worker reads the latest successful snapshot and retries.

**Auditability.** Every reasoning step is an immutable object in S3. Six months from now, the question "why did the agent decide it was a database issue?" has an exact answer — load that snapshot and replay.

**Replayability.** Want to test a new system prompt? Load a historical snapshot, swap the system_prompt object, run the loop, see what changes. Want to debug a wrong path? Fork from the snapshot just before the bad decision and try alternative tool calls.

These properties don't fall out of "agent framework." They fall out of *immutable content-addressable storage with atomic writes* — which is why the data layer is the unfair advantage, not the prompt engineering.

## Component dependencies

```
Dashboard (Next.js)
    ↓ HTTPS
Next.js API routes ──────────────┐
    ↓                            │
Supabase Auth + Postgres         │
                                 │
Control plane (FastAPI) ←────────┘
    ↓
    ├─→ DuckDB → S3 (Iceberg)
    ├─→ Job queue (Postgres SELECT FOR UPDATE SKIP LOCKED)
    └─→ Gemini API

OTLP receiver (Go)
    ↓
    ├─→ Postgres (auth tokens)
    └─→ S3 (Iceberg writes)

Anomaly watcher (Python, separate process)
    ↓
    ├─→ Postgres (read agents)
    ├─→ DuckDB → S3 (run scope queries)
    └─→ Job queue (push anomaly events)

Trigger router (Python, separate process)
    ↓
    ├─→ Job queue (consume)
    ├─→ Postgres (read agents, write sessions)
    └─→ S3 (write initial snapshots)

Agent runtime worker (Python, separate process)
    ↓
    ├─→ Job queue (consume snapshot-ready events)
    ├─→ S3 (read/write snapshots, objects, artifacts)
    ├─→ DuckDB → S3 (tool: query_telemetry)
    ├─→ Gemini API (LLM calls)
    ├─→ GitHub MCP (subprocess or HTTP)
    └─→ Slack MCP (subprocess or HTTP)
```

For local dev, all of these can run in `infra/docker-compose.yml`. For production demo, the Python services co-locate on one Fly.io VM.

## Job queue: pick Postgres

Use Postgres as the queue. The `SELECT ... FOR UPDATE SKIP LOCKED` pattern is well-known, ACID-correct, supports visibility timeouts via simple timestamp columns, and means one less service to operate. Don't pull in Redis or SQS for the prototype.

```sql
-- jobs table
CREATE TABLE jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL,
  kind TEXT NOT NULL,           -- 'anomaly', 'cron', 'slack_message', 'snapshot_ready'
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  visible_at TIMESTAMPTZ DEFAULT now(),  -- for delayed/retried jobs
  consumer_id TEXT,             -- which worker has it locked
  locked_at TIMESTAMPTZ,
  attempts INT DEFAULT 0
);

-- consume pattern (in Python via asyncpg):
-- BEGIN;
-- SELECT * FROM jobs
--   WHERE visible_at <= now() AND consumer_id IS NULL
--   ORDER BY created_at
--   LIMIT 1
--   FOR UPDATE SKIP LOCKED;
-- UPDATE jobs SET consumer_id = $1, locked_at = now(), attempts = attempts + 1 WHERE id = ...;
-- COMMIT;
```

A separate "reaper" task unlocks jobs whose `locked_at` is older than 5 minutes (visibility timeout) so crashed workers don't strand jobs.

## Connecting to the v1 codebase

The existing `aaryans` branch has working code for:

- Snapshot engine (`backend/src/agent/snapshot.py`, `object_store.py`) — port and adapt for tenant-scoping
- Iceberg writer (`backend/src/iceberg_writer.py`) — extend for OTLP-shaped tables
- DuckDB query layer (`backend/src/query.py`) — wrap with tenant_id enforcement
- MCP server (`mcp-server/`) — keep, extend with `read_artifact`
- Go ingestion (`go-ingestion/`) — refactor: keep batching pattern, replace bespoke event format with OTLP

The dashboard from v1 is React + custom CSS — for v2, rewrite as Next.js + shadcn from scratch. The v1 dashboard is too tied to the simulator demo to port directly.

The simulator (`simulator/`) is no longer needed as a primary path — the OpenTelemetry Demo provides real traffic. Keep the simulator code in `aaryans` branch for reference but don't port to `v2`.
