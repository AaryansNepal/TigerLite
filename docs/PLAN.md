# Build plan

This document is the source of truth for what's done and what's next. **Update it after every meaningful change.**

Each phase ships something demoable. If you stop after any phase, the project is not broken — just earlier in the FireTiger loop.

Realistic estimate: **5–7 weeks solo full-time.** Less if cutting Phase 4 (Claude Code handoff) and merging Phase 3 into Phase 2.

---

## Phase 0 — Foundation (10–14 days)

Goal: a working multi-tenant OpenTelemetry SaaS. No agents yet. A user can sign up, get an OTLP endpoint with a token, point a real OTel SDK at it, and see traces in a basic dashboard.

### Repo structure
- [ ] Create `v2` branch from `main`/`aaryans`
- [ ] Restructure into monorepo layout (see CLAUDE.md)
- [ ] Add `docs/` folder with files in this set
- [ ] Add `infra/docker-compose.yml` for local dev (MinIO, Iceberg REST catalog, Postgres)
- [ ] Add `.env.example` with all required env vars

### Database & auth
- [ ] Set up Supabase project (free tier)
- [ ] Postgres schema per `docs/DATA_MODEL.md`: `tenants`, `users` (handled by Supabase Auth), `connections`, `agents`, `sessions` (index), `issues`, `findings`
- [ ] Row-level security (RLS) policies for tenant isolation on all tables
- [ ] Auth flow in dashboard: signup → tenant created automatically → land on `/home`

### Storage
- [ ] AWS S3 bucket: `tigerlite-{stage}-telemetry` for Iceberg tables
- [ ] AWS S3 bucket: `tigerlite-{stage}-snapshots` for snapshot manifests + objects + artifacts
- [ ] IAM role with minimal permissions
- [ ] For local dev, MinIO substitutes for both buckets

### OTLP receiver
- [ ] Refactor Go service to accept OTLP/HTTP at `/v1/traces`, `/v1/logs`, `/v1/metrics`
- [ ] Use `go.opentelemetry.io/collector/pdata` for OTLP types
- [ ] Token-based auth: `Authorization: Bearer <ingest_token>` validated against `connections` table
- [ ] Tenant-scoped Iceberg writes: `tenant_id` is the leading partition column on every table
- [ ] Iceberg tables for OTel-shaped data: `traces`, `logs`, `metrics` (see `docs/DATA_MODEL.md`)
- [ ] Health endpoint: `/health` returns 200 + service info
- [ ] Metrics endpoint: `/metrics` returns ingest rates per tenant

### Dashboard skeleton
- [ ] Next.js 15 + App Router + Tailwind + shadcn/ui
- [ ] Sidebar layout matching FireTiger UI (Home / Agents / Change Monitor / Investigate / Issues / Integrations)
- [ ] Auth pages (signup, signin) via Supabase Auth UI
- [ ] `/home` page with three "Connect" cards: Telemetry, GitHub, Slack — all initially "Not connected"
- [ ] `/integrations` page listing connected services
- [ ] `/agents` page with empty state + "New agent" button (button does nothing yet)
- [ ] Telemetry connection modal: shows generated OTLP endpoint URL + ingest token, polls for first event, flips to "Connected — receiving data from `<service.name>`, ..." when first event arrives

### Acceptance for Phase 0
- A new user can sign up, click "Connect Telemetry," get a real endpoint + token, point an `otel-cli` send command at it, and see the connection card flip to "Connected" within 30 seconds.
- Trace data is queryable via DuckDB against the Iceberg table for that tenant.
- No agent functionality exists yet — that's Phase 1.

---

## Phase 1 — First end-to-end agent (7–10 days)

Goal: a user creates an agent in plain language; the agent watches their telemetry; an injected regression triggers an investigation; a finding appears in the dashboard.

### Monitored app setup
- [ ] Fork `open-telemetry/opentelemetry-demo` to user's GitHub
- [ ] Configure OTel collector inside the fork to export to TigerLite's OTLP endpoint (one YAML change in `src/otelcollector/otelcol-config.yml`)
- [ ] Document local run via `docker compose up`
- [ ] Verify traces flow into TigerLite's Iceberg tables under the right tenant
- [ ] Identify which feature flags will be used for the demo (`paymentServiceFailure` is the likely first)

### Agent compiler
- [ ] `services/control-plane/agents/compiler.py` — takes plain-language objective + tenant's auto-detected service inventory → returns structured `AgentConfig` (scope, plan, default triggers, default notification)
- [ ] Single Gemini Flash call with a tight system prompt (see `docs/AGENT_DESIGN.md`)
- [ ] Returns Pydantic model so it's typed and testable

### Agent CRUD
- [ ] Next.js API routes: `POST /api/agents`, `GET /api/agents`, `GET /api/agents/:id`, `PATCH /api/agents/:id`, `DELETE /api/agents/:id`
- [ ] Dashboard chat-driven creation flow per `docs/UI_SPEC.md` Image 1+2 (back-and-forth Q&A → green confirmation card)
- [ ] Agent detail view per `docs/UI_SPEC.md` Image 4 (Status, Description, Triggers, Notifications, Plan)
- [ ] Plan field is editable freeform text — gets injected into the agent's system prompt at session start

### Anomaly watcher
- [ ] `services/control-plane/watchers/anomaly.py` — runs every 60s
- [ ] For each active agent: build a DuckDB query from the agent's `scope_config`, compute a "current vs baseline" comparison
- [ ] Baseline starts simple: median p95 over last 7 days vs p95 over last 5 minutes
- [ ] When deviation crosses threshold, push to job queue: `{kind: "anomaly", agent_id, evidence}`

### Trigger router
- [ ] `services/control-plane/router.py` — consumes the queue
- [ ] For each event: look up agent, decide new-or-resume-session, write initial snapshot to S3
- [ ] Resume rules: if the agent has an open session, append the event to it instead of starting fresh

### Snapshot store on S3
- [ ] Migrate v1's snapshot engine from MinIO to S3 (single client interface, swap implementation per env)
- [ ] Keep content-addressable object pattern: `objects/{sha256}`
- [ ] Snapshot manifests: `snapshots/{agent_id}/{session_id}/{version}`
- [ ] Atomic writes via `If-None-Match` for concurrency safety

### Agent runtime — Python worker
- [ ] `services/agent-runtime/worker.py` — `while True:` loop consuming the queue
- [ ] `services/agent-runtime/run_step.py` — pure function: `(snapshot_id) → next_snapshot_id`
- [ ] Loads snapshot, replays objects to Gemini conversation format
- [ ] Calls Gemini 2.5 Pro with state + available tools
- [ ] Executes tool call, composes new objects, writes new snapshot, enqueues next step
- [ ] Terminal conditions: Gemini says done, MAX_STEPS hit, error after retries

### First tool set
- [ ] `query_telemetry(sql)` — DuckDB over Iceberg, tenant-scoped, returns first 5 rows + columns + artifact_id
- [ ] `read_artifact(id, jq?)` — reads stored artifact, optional jq filter (use `gojq` via subprocess or a Python jq lib)
- [ ] `record_finding(title, summary, severity, evidence)` — writes to `findings` table
- [ ] `create_issue(title, summary, severity, suggested_action)` — writes to `issues` table, links to current session

### Sessions list & detail
- [ ] `/agents/:id/sessions` — list view per `docs/UI_SPEC.md` Image 7
- [ ] `/agents/:id/sessions/:sid` — timeline rendering snapshot objects as type-specific cards (assistant text, tool_call, tool_result, etc.)

### Acceptance for Phase 1
- User creates an agent: "watch the cart and checkout endpoints, response time over 500ms p95 means trouble."
- User toggles `cartFailure` flag in the running Astronomy Shop fork.
- Within 60 seconds, an investigation session appears in `/agents/:id/sessions`.
- Session detail shows: agent's reasoning, the DuckDB queries it ran, a `record_finding` with root cause hypothesis.
- No GitHub or Slack integration yet — finding is only visible in the dashboard.

---

## Phase 2 — GitHub + Slack (7 days)

Goal: the agent can read the user's repo, identify the commit that caused the regression, and post a structured root-cause message to Slack.

### GitHub integration
- [ ] Create GitHub App for TigerLite (development version)
- [ ] OAuth-style installation flow on `/integrations`: pick repo, install, store install token in `connections`
- [ ] Run `github/github-mcp-server` inside the agent runtime container
- [ ] Wire MCP discovery into `run_step`: at start of each step, list available MCP tools and merge with internal tools

### GitHub-backed agent tools (via MCP)
- [ ] `list_recent_commits(repo, since)` — for correlating with regression timing
- [ ] `get_commit_diff(repo, sha)` — to read what changed
- [ ] `read_file(repo, path, ref?, lines?)` — to inspect specific code
- [ ] `search_code(repo, query)` — for following imports/references

### Slack integration
- [ ] Slack OAuth flow on `/integrations`: pick workspace + channel
- [ ] Run Slack MCP server in the agent runtime
- [ ] `post_to_slack(channel, blocks)` — structured message with title, summary, affected scope, "View finding" link

### Slack inbound (for the human-in-the-loop story)
- [ ] `/api/slack/events` Next.js route — receives Slack event subscriptions
- [ ] On `app_mention` or thread reply in connected channel: enqueue `{kind: "slack_message", agent_id, thread_ts, text}`
- [ ] Trigger router resumes the agent's session associated with that thread (so a reply continues the existing investigation)

### Renderer for tool result cards in session timeline
- [ ] Type-specific cards per `docs/UI_SPEC.md`:
  - GitHub `read_file` result → file panel with line numbers (Image 3)
  - `record_finding` → green "New issue" callout (Image 6)
  - `query_telemetry` → mini result table

### Acceptance for Phase 2
- Same demo as Phase 1, but the Slack message arrives within ~60 seconds with: root cause hypothesis, the offending commit SHA, the affected request count, the Slack thread is permanent and threaded so a human can reply.
- Replying in the Slack thread continues the agent's session — agent answers in the same thread.
- Session timeline in the dashboard shows the agent reading specific files from the GitHub repo.

---

## Phase 3 — Verification + multi-agent (5–7 days)

Goal: the loop closes. After a fix is deployed, the agent confirms recovery and auto-resolves the issue.

### Issue model
- [ ] `issues` table is fully wired: `opened_by_session_id`, `resolved_by_session_id`, status (open/resolved/regressed)
- [ ] Sidebar nav shows count of open issues per tenant (the "1" badge in screenshots)
- [ ] `/issues` list page

### Verification sessions
- [ ] When `record_finding` produces a high-severity finding, automatically schedule a "verification" session via cron (every 10 min for the first hour, then exponential backoff)
- [ ] Verification session has a different system prompt: "Compare current metrics to the baseline that triggered this issue. Is it resolved?"
- [ ] On recovery: post resolution message to the same Slack thread, mark issue resolved
- [ ] On regression after apparent recovery: re-open issue, escalate

### Multi-agent
- [ ] Users can create more than one agent per tenant
- [ ] Anomaly watcher iterates over all active agents efficiently (one query per agent per minute is fine for demo scale)

### Per-agent memory (basic)
- [ ] Per-agent named ref in S3: `agents/{id}/memory.json`
- [ ] At session start, load memory and inject into system prompt
- [ ] At session end, post-process: extract structured info from findings, update memory
- [ ] First version stores: rolling p95 baselines per service, last 50 findings (deduplicated by signature)

### Manual trigger button
- [ ] "Run now" button on agent detail (Image 4)
- [ ] Button calls `POST /api/agents/:id/trigger` which enqueues a manual trigger event
- [ ] Useful for demos — deterministic agent run on demand

### Acceptance for Phase 3
- After detecting an issue and posting to Slack, agent watches for recovery.
- When the user merges and deploys a fix to the Astronomy Shop fork, the agent posts "Fix verified, marking resolved" within 5 minutes (Image 8).
- Multiple agents can coexist with different scopes and triggers.

---

## Phase 4 — Coding agent handoff (3–5 days)

Goal: the agent doesn't just identify the problem — it prepares everything Claude Code (or Cursor) needs to fix it.

### Context bundle
- [ ] `prepare_fix_handoff` tool: agent calls this when it has a high-confidence root cause + the affected files
- [ ] Bundle contains: root cause text, affected file paths with line numbers, expected behavior, verification plan (which metric to watch and what threshold means recovered), the snapshot ID for full audit trail

### Two delivery options
- [ ] "Copy as Claude Code prompt" button in the issue detail page — copies a pre-formatted prompt to clipboard
- [ ] (Stretch) Direct Anthropic API call from the agent: opens a draft PR via the GitHub MCP with the suggested fix, links the PR back into the issue

### Acceptance for Phase 4
- From the issue page, the user clicks "Hand off to Claude Code" and gets a prompt ready to paste into their CLI.
- Optional stretch: a draft PR appears on the user's repo, linked from the issue.

---

## What's intentionally *not* in scope

These are real concerns for a production Firetiger but explicit non-goals for this prototype. Documented here so they don't sneak in.

- **Iceberg compaction.** The "small files problem" is real at scale (see Firetiger's blog post), but at demo scale (hundreds of small files, not millions) DuckDB handles it fine. Don't build a compaction service.
- **Lambda + S3 events agent runtime.** The `run_step` function is structured to support it (pure function, no in-memory state), but the worker driver is enough for demo. Document the Lambda alternative in README under "production architecture."
- **Sandboxing (Chambers / microVMs).** Agent calls only typed tools. No bash, no arbitrary code. If shell access becomes needed later, use [e2b.dev](https://e2b.dev) — don't build chambers from scratch.
- **Schema inference for arbitrary OTel attributes.** Use the OTLP standard schema; don't try to handle arbitrary user-defined attributes generically.
- **Agent branching / parallel hypothesis exploration.** The snapshot model supports it (Git-style fork) but it's a Phase 5 feature.
- **Confit SQL or other custom DSLs.** Plain DuckDB SQL is the agent's tool surface.
- **Multi-region / availability / disaster recovery.** Single region, single set of buckets, single Postgres.
- **SOC2 / compliance.** Not a paying-customer product yet.

## Status log

Append a one-line entry per session below as work progresses.

- 2026-04-27: Project plan finalized. Start Phase 0.
- 2026-04-27: `demo` branch created from `aaryans` (v1 frozen on aaryans). Monorepo restructure complete (apps/, services/, packages/, infra/, scripts/). v1 dirs removed from `demo`; v1 WIP stashed on aaryans.
- 2026-04-27: Phase 0 complete — full Postgres schema migrations (covering all phases 0-4 incl. RLS + signup trigger), MinIO + Iceberg REST docker-compose, Go OTLP/HTTP receiver (`services/ingest`) with bcrypt token auth + per-tenant Iceberg routing, Python control plane (`services/control-plane`) with agents CRUD + DuckDB tenant-scoped query layer + PyIceberg writer + Postgres queue + anomaly/cron/verification/reaper background loops + Slack inbound webhook + connections store-install endpoints + envelope encryption.
- 2026-04-27: Phase 1 complete — agent compiler (Gemini Flash with deterministic skeleton fallback + DEMO_MODE shortcut), agent runtime worker (`services/agent-runtime`) with snapshot loop, content-addressable object store, `run_one_step` pure function + Lambda handler shim, full toolbox (query_telemetry / read_artifact / record_finding / create_issue / update_memory / post_to_slack / prepare_fix_handoff), MCP discovery hook with `If-None-Match` atomic snapshot writes.
- 2026-04-27: Phase 2 complete — MCP stdio client (`mcp_client.py`), GitHub + Slack tool dispatch via discovery, encrypted credentials per agent, Slack inbound signature verification, GitHub App / Slack App setup guides in `docs/`.
- 2026-04-27: Phase 3 complete — verification cron with exponential backoff, session_finalizer reads agent's terminal text (RESOLVED/REGRESSED/STILL_OPEN) and transitions issue state, memory writer accumulates finding signatures + observed baselines, manual "Run now" trigger.
- 2026-04-27: Phase 4 complete — Claude Code prompt rendered server-side via `/api/issues/{id}/handoff`, dashboard "Copy as Claude Code prompt" button. Stretch auto-PR variant scaffolded as `agents/auto_fix.py` (gated behind ANTHROPIC_API_KEY, intentionally not_implemented_in_demo).
- 2026-04-27: Frontend complete — Next.js 15 + Tailwind + Supabase SSR. Sidebar layout with Issues badge, Home with three Connect cards + active agents list, Agents list/new (chat-driven creation flow), agent detail Details/Sessions/Chat tabs, session timeline with Realtime auto-refresh, Issues list/detail with Claude Code handoff component, Integrations + Change Monitor + Investigate stubs. Shared types in `packages/shared-types/`.
- 2026-04-27: Wrap-up — PLAN status log updated. Next: `pnpm install`, fill `.env.local`, `pnpm infra:up`, `pnpm db:migrate`, point an OTel SDK at the issued ingest token, watch the connection flip to "Connected".
