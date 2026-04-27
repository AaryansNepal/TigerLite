# TigerLite v2 — project guide for Claude Code

You are helping build **TigerLite v2**, a working prototype of an AI-powered operations platform inspired by [Firetiger](https://www.firetiger.com). Users connect their OpenTelemetry data, GitHub repo, and Slack workspace, then create agents in plain language ("checkout flow should always be fast") that autonomously monitor production, investigate problems, identify root causes, and post findings to Slack.

This file is your orientation. Read it first. The detailed design lives in `docs/`.

## What this project is

A **demo-able prototype** that closes the observe → understand loop autonomously. The user defines an agent in one sentence; the agent watches OpenTelemetry data 24/7; when something breaks, the agent investigates, correlates against recent commits via the GitHub MCP, and posts a structured root-cause finding to Slack — without anyone setting up dashboards, thresholds, or runbooks.

This is **not** a Datadog clone. The architectural inspiration is Firetiger's "outcome engineering" thesis: agents own operational outcomes, not dashboards.

## What this project is built on

This is the **v2** rewrite of [`AaryansNepal/TigerLite`](https://github.com/AaryansNepal/TigerLite). The v1 prototype on the `aaryans` branch already established:

- A Go ingestion service (channel-based batching, stdlib HTTP)
- Apache Iceberg on MinIO with REST catalog, queried via DuckDB + `iceberg_scan()`
- A Git-inspired snapshot agent (immutable, content-addressable reasoning chains)
- An MCP server exposing the data lake to Claude Desktop
- A React dashboard with SSE
- A simulator with 10 fake customers and a "trigger bad deploy" scenario

**The v1 bones are sound.** v2 keeps the snapshot engine, Iceberg + DuckDB pipeline, MCP server, and dashboard. v2 changes: real OTLP intake (no simulator), multi-tenant data model, agents as first-class persistent resources, GitHub + Slack MCP integrations, verification loop, real auth.

Work on a new branch `v2`. Leave `aaryans` frozen as the v1 reference.

## Where to find what

Read the relevant doc when starting work on a topic. Don't reload everything every session.

| File | What's in it |
|------|--------------|
| `docs/PLAN.md` | Phased build plan with checkboxes. Update as you go. **This is the source of truth for what's done and what's next.** |
| `docs/ARCHITECTURE.md` | System architecture. Three planes (data, trigger, agent runtime). Component diagram. Hosting topology. |
| `docs/AGENT_DESIGN.md` | The agent runtime in depth. The snapshot loop. Worker pseudocode. Triggers. Memory. Tools. |
| `docs/DATA_MODEL.md` | Postgres schema. Iceberg tables. S3 layout. Object types. |
| `docs/TECH_STACK.md` | Every technology choice with the reason. Reference when "why X not Y" comes up. |
| `docs/DEMO.md` | What the demo proves. The narrative arc. Success criteria. |
| `docs/UI_SPEC.md` | Screen-by-screen spec based on visual mockups. Pin the screenshots in `docs/design/`. |
| `docs/MONITORED_APP.md` | How to set up the forked OpenTelemetry Demo (the app the agent watches). |

## Critical decisions (do not re-debate)

- **Agent runtime is a long-running Python worker, not AWS Lambda.** Lambda + S3 events is the architecturally correct production design (matches Firetiger exactly), but it adds a week of AWS plumbing for an audience that won't notice. Worker has identical functional properties (stateless step execution, snapshot in/out). Lambda version stays as a 20-line `lambda_handler.py` shim that wraps the same `run_one_step` function. Documented in README under "production architecture."
- **Auth + Postgres = Supabase, not Clerk.** One service for auth + DB + Realtime. Free tier is enough.
- **Monitored app = forked OpenTelemetry Demo (Astronomy Shop).** Do not write a custom storefront. The fork has built-in feature flags for failure injection (cartFailure, paymentServiceFailure) — use those to drive the demo regression.
- **No "Chambers" or microVMs.** Agent calls typed tools only — no shell access. Sandboxing isn't needed at this scope. If shell access is added later (Phase 4 code-execution handoff), reach for [e2b.dev](https://e2b.dev) rather than building chambers.
- **Tool result handling: truncate + saved artifacts pattern from day one.** Cap tool results at ~5000 tokens, store full result as content-addressed S3 artifact, give the agent a `read_artifact(id, jq?)` tool. This is non-optional for a Gemini agent doing real DuckDB queries.
- **LLM is Gemini.** Gemini 2.5 Pro for agent reasoning, Gemini Flash for the agent compiler and other cheap calls.
- **MCP servers used:** GitHub (`github/github-mcp-server`), Slack (community reference server), and TigerLite's own internal MCP (DuckDB queries + artifacts).

## Conventions

**Branch:** all v2 work happens on `v2`. Do not commit to `aaryans`.

**Repo layout (target — refactor incrementally toward this):**
```
tigerlite/
├── CLAUDE.md
├── docs/
├── apps/
│   └── dashboard/          # Next.js 15 + Tailwind + shadcn/ui
├── services/
│   ├── ingest/             # Go OTLP receiver
│   ├── control-plane/      # FastAPI — agent CRUD, query layer
│   └── agent-runtime/      # Python worker — the snapshot loop
├── packages/
│   └── shared-types/       # TypeScript types shared between dashboard and Next.js API routes
├── infra/
│   ├── docker-compose.yml  # local dev: MinIO, Iceberg catalog, Postgres
│   └── terraform/          # AWS resources (S3 buckets, IAM)
└── scripts/
```

**Languages by service:**
- Frontend: TypeScript (Next.js, React 19, App Router)
- Control plane API: Python (FastAPI) — heavy logic, LLM calls, query orchestration
- OTLP receiver: Go (use `go.opentelemetry.io/collector/pdata`)
- Agent runtime: Python (async)
- Glue/scripts: shell, with light Python where needed

**Style:**
- Plain prose comments. No emoji in code.
- Type everything. Pydantic models for Python; Zod for TypeScript at API boundaries.
- Async/await everywhere in Python (no sync DB calls in request paths).
- Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`).

**Multi-tenancy is not optional, ever.** Every query, every storage path, every API call must be tenant-scoped from the first commit. Do not introduce single-tenant code paths "to save time." The cost of retrofitting tenancy is brutal.

## Anti-patterns (don't do these)

- Don't add specialized one-off tools to the agent. The toolbox stays small: `query_telemetry`, `read_artifact`, `read_file`, `list_recent_commits`, `get_commit_diff`, `post_to_slack`, `record_finding`, `create_issue`. Resist the urge to add `get_top_5_slow_endpoints` etc. — let the agent express that as SQL.
- Don't bypass the snapshot model with "shortcuts." Every reasoning step is an immutable object. No mutable session state in worker memory.
- Don't hold MCP connections across worker steps. Per Firetiger's "atomic discovery per turn" pattern, re-establish MCP at the start of each step, query tools, run, tear down. Slightly more overhead per call; way simpler operationally.
- Don't store telemetry in Postgres. Telemetry is OpenTelemetry-native, lands in Iceberg, queried via DuckDB. Postgres is for control plane only (tenants, agents, sessions index, connections, issues).
- Don't put the OTLP receiver on Vercel. It needs persistent processes for gRPC streams.
- Don't try to make the dashboard "pretty" before the data flow works. UI polish is the last 10%, not the first.

## Current status

See `docs/PLAN.md` for the phase checklist. Update it after every meaningful change.

## Working with the user (Aaryan)

- Aaryan is technical and has read Achille Roussel's Firetiger blog posts in detail. Speak at that level.
- The demo target is "presentable in class" — meaning a real working SaaS that strangers could sign up to, but presented from Aaryan's laptop. Don't over-engineer for hyperscale.
- When in doubt about scope, cut. The demo lands when the Slack message arrives within 60 seconds of injecting the failure. Everything else is in service of that moment.

When you finish a meaningful unit of work, summarize in chat what changed, what's next, and what's still unclear. Then update `docs/PLAN.md`.
