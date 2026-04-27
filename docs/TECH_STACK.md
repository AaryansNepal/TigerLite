# Tech stack

Every choice with reasoning. Reference this when "why are we using X not Y" comes up.

## Frontend

**Next.js 15 (App Router) + React 19 + TypeScript.** Mainstream, Vercel-native, great DX, first-party support for OTel via `@vercel/otel` (matters because the dashboard *itself* should emit traces eventually). App Router because Server Components let us colocate auth-aware queries with the components that render them, avoiding a layer of API plumbing for read paths.

**Tailwind CSS + shadcn/ui.** The Firetiger UI in the screenshots is essentially this stack. shadcn gives accessible, restrained primitives we own (it's "copy components into your repo," not a dependency). Tailwind for everything else. Stick to the default design tokens — don't customize the palette in early phases.

**Hosting: Vercel free tier.** Free SSL, GitHub-integrated deploys, edge function support if we want it later.

## Auth + Database

**Supabase.** One service for: Postgres (managed), Auth (with OAuth providers built in), Realtime (websockets for live dashboard updates), Storage (we won't use this — S3 is better for our needs). Free tier is generous: 500 MB database, 50,000 monthly active users, 2 GB bandwidth. Enough for a demo.

**Why not Clerk?** Clerk's UI is more polished but we'd still need Postgres separately. Supabase consolidates. Auth UI we use shadcn-styled login forms calling Supabase Auth APIs directly — `<SignIn />` from Clerk is nicer out of the box but we're not optimizing for that.

**Why not Auth.js (NextAuth)?** It's the right call if you have your own DB and just want auth. We don't — we want managed Postgres.

**Row-level security from day one.** Supabase makes this turnkey via `auth.uid()` in RLS policies. If you skip RLS and rely on application-level enforcement, every query is a potential cross-tenant leak. RLS makes the database the bouncer.

## Data lake

**Apache Iceberg + AWS S3 + DuckDB.** This is the Firetiger architecture, full stop, and it's the most architecturally interesting bit we're carrying over from TigerLite v1.

- **Iceberg** for the table format. Atomic schema evolution, partition evolution, time travel, an open standard with broad query engine support.
- **S3** for storage. Cheap, durable, infinite. Free tier (5 GB) easily covers demo.
- **DuckDB + `iceberg_scan()`** for queries. In-process, no cluster to operate, fast on selective columnar reads. Great for agents that run hundreds of queries per investigation (the access pattern Firetiger optimized for).

**For local dev: MinIO** as a drop-in S3 replacement. The S3 client config swaps based on env var.

**Iceberg REST catalog**: `tabulario/iceberg-rest` Docker image. Runs alongside the OTLP receiver. Lightweight, file-backed catalog state on disk for demo. Production would use AWS Glue or Nessie.

**Why not ClickHouse?** Better single-engine performance but it's a database, not a data lake. You'd be locked in. Iceberg lets DuckDB, Spark, Trino, Athena all read the same tables.

**Why not Postgres for telemetry?** Cardinality explosion on attributes. Wrong tool for time-series at any volume.

## Telemetry intake

**Go.** Already chosen in v1 and the right call. Channel-based batching, `sync/atomic` counters, multi-stage Docker build to a ~15MB image. Go's stdlib HTTP and the official OTel collector libraries (`go.opentelemetry.io/collector/pdata`) make OTLP intake straightforward.

**OTLP/HTTP first, gRPC later.** OTLP/HTTP is easier to debug (curl-able), works through any HTTP load balancer, doesn't need protobuf tooling. gRPC support can come in Phase 2 if we want to flex on performance, but most OTel SDKs default to HTTP fine.

## Backend services

**Python + FastAPI for the control plane and agent runtime.** Python wins for: LLM SDKs (Gemini, Anthropic, OpenAI all first-class), data tooling (DuckDB Python bindings are official), `gojq`/`pyjq` for the artifacts pattern. FastAPI for typed APIs with automatic OpenAPI docs. `asyncpg` for Postgres without ORM bloat.

**Why not Node for everything?** TypeScript-on-the-server is fine but Python's ML/data ecosystem is still ahead, and the agent runtime is Python-shaped work. We use Node where it earns its place (Next.js API routes co-located with the dashboard).

**Why not Rust?** Rewards in scale, costs in dev time. Wrong tradeoff for a demo prototype. Go covers the one place we want raw performance (ingest).

## LLM

**Gemini 2.5 Pro** for agent reasoning. **Gemini Flash** for the agent compiler and other cheap utility calls. User's choice and a good one — generous free tier (15 RPM, 1 million tokens/day on Pro), 1M-token context useful for replaying long agent state without summarization tricks, native function-calling support, JSON mode for the structured outputs.

**Always set `temperature=0` for tool-calling steps.** Determinism matters for agent reasoning — you want the same input to produce the same plan.

**Don't use Anthropic for the agent itself.** Save Anthropic API for the Phase 4 Claude Code handoff specifically. Gemini for the in-loop agent keeps cost and rate limits separate.

## MCP

**GitHub: `github/github-mcp-server`** (official). Handles the OAuth/install token, exposes typed tools (`list_commits`, `get_file_contents`, `create_pull_request`, etc.). Run as a subprocess from the agent runtime container.

**Slack: community reference server** (`modelcontextprotocol/servers/slack`). Same pattern.

**Internal: extend v1's MCP server.** Add `read_artifact(id, jq?)` per Firetiger's "Agent Engineering Patterns" post.

**Atomic discovery per turn.** At the start of each agent step, the worker queries each MCP server for available tools, merges with internal tools, sends the combined list to Gemini. ~100-500ms overhead per step. Don't try to keep MCP connections persistent across steps — agent runtime is conceptually ephemeral (stateless step execution), and persistent MCP connections fight that.

## Hosting

**Free-tier composition for demo:**

- Vercel free: dashboard + Next.js API routes
- Fly.io free shared-cpu-1x: OTLP receiver, control plane (FastAPI), agent worker, Iceberg REST catalog (one VM, multiple processes)
- AWS S3 free tier: telemetry bucket + snapshots bucket
- Supabase free: Postgres + Auth + Realtime
- User's laptop or DigitalOcean droplet: Astronomy Shop fork

Total: $0/month for 12 months. After AWS free tier expires, ~$5/month.

**Don't use AWS Lambda for the agent runtime.** It's the architecturally correct choice (matches Firetiger exactly) and adds a week of plumbing. The worker pattern has identical functional properties (stateless step execution, snapshot in/out). Lambda version stays as a documented `lambda_handler.py` wrapper.

**Don't use Kubernetes.** Even for "production-like" deployment, Fly.io machines or Railway are fine and simpler.

## Local dev

**Docker Compose** for local infrastructure: MinIO (S3 substitute), Iceberg REST catalog, Postgres (separate from Supabase for dev). Run dashboard via `pnpm dev`. Run Python services natively (`uvicorn` for FastAPI, `python worker.py` for the runtime) for fast restart.

**`pnpm` over `npm`.** Faster, disk-efficient.

**`uv` over `pip`/`poetry`.** Order-of-magnitude faster Python deps. `uv pip install` for everything.

## Testing

**Pytest** for Python. Property-based tests (Hypothesis) for the snapshot loop's pure-function nature — generate random valid snapshots, run a step, verify invariants.

**Vitest** for TypeScript.

**Playwright** for end-to-end demo scenario validation — script the full "user signs up, connects, creates agent, triggers regression, sees Slack message" flow as a regression test before each release.

**Don't over-test the agent's reasoning.** Gemini outputs are non-deterministic enough that exact-match assertions are brittle. Test the *plumbing* (snapshot loop, queue, tool execution) thoroughly. Validate agent reasoning with eval-style scenario runs, accepting probabilistic pass rates.

## Observability for TigerLite itself

Eat your own dog food: TigerLite emits OTel traces and ingests them into a `meta` tenant. The agent runtime, control plane, and OTLP receiver all instrument with `@opentelemetry/api`. When something breaks in TigerLite, you investigate it with TigerLite. Same dogfooding move Firetiger calls out in their March 1 incident postmortem.

## Things explicitly not used

- **Datadog, New Relic, Honeycomb, Sentry.** We *are* observability for the demo. Using one of these would be ironic.
- **Redis.** Postgres is the queue. One less service to operate.
- **Kafka.** Massively over-architected for this scale.
- **GraphQL.** REST + Next.js Server Actions is enough.
- **Prisma / Drizzle / SQLAlchemy.** Raw SQL via `asyncpg` (Python) and `postgres-js` (TypeScript). We're going to write enough custom queries that an ORM is dead weight.
- **Terraform / Pulumi.** For demo, infrastructure is small enough to manage with shell scripts and the AWS Console. Terraform comes in if/when we need reproducibility.
