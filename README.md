# TigerLite v2

> AI-powered operations platform. Connect your OpenTelemetry data, GitHub repo,
> and Slack workspace, then create autonomous agents in plain language. Agents
> watch your production telemetry 24/7, investigate anomalies, correlate against
> recent commits, and post structured root-cause findings to Slack — without
> dashboards, thresholds, or runbooks.
>
> Inspired by [Firetiger](https://www.firetiger.com).

This branch (`demo`) is the v2 rewrite. The legacy v1 prototype lives on
[`aaryans`](https://github.com/AaryansNepal/TigerLite/tree/aaryans).

## Repository layout

```
tigerlite/
├── CLAUDE.md                  # Orientation for Claude Code (read this first)
├── docs/                      # Phase plan, architecture, agent design, schema, UI spec
├── apps/
│   └── dashboard/             # Next.js 15 + Tailwind + shadcn/ui
├── services/
│   ├── ingest/                # Go OTLP/HTTP receiver
│   ├── control-plane/         # Python/FastAPI — CRUD, queue, watchers
│   ├── agent-runtime/         # Python — snapshot loop worker
│   └── mcp-internal/          # TigerLite's own MCP server (DuckDB + artifacts)
├── packages/
│   └── shared-types/          # TypeScript types shared between dashboard and APIs
├── infra/
│   ├── docker-compose.yml     # Local dev: MinIO + Iceberg REST catalog
│   ├── migrations/            # Postgres schema (apply to Supabase)
│   └── iceberg-rest/          # Catalog config
└── scripts/                   # Shell helpers (migrate, seed, etc.)
```

## Quick start (local dev)

Prereqs: Docker, Node 20+, pnpm 9+, Python 3.11+, Go 1.22+, [`uv`](https://github.com/astral-sh/uv).

```bash
# 1. Copy env template and fill in real values
cp .env.example .env.local
# Edit .env.local — at minimum set SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL,
# and (when reaching Phase 1) GEMINI_API_KEY.

# 2. Bring up local infra (MinIO + Iceberg REST catalog)
pnpm infra:up

# 3. Apply Postgres schema to Supabase
pnpm db:migrate

# 4. Install dashboard deps and start dev server
pnpm install
pnpm dev

# 5. (Phase 1+) start the control plane and agent runtime
cd services/control-plane && uv sync && uv run uvicorn tigerlite_control.main:app --reload --port 8000
cd services/agent-runtime && uv sync && uv run python -m tigerlite_runtime.worker

# 6. (Phase 0+) start the OTLP receiver
cd services/ingest && go run ./cmd/ingest
```

## Phases

| Phase | Goal | Demo lands |
|-------|------|------------|
| 0     | Multi-tenant SaaS foundation + OTLP intake | User can sign up, get an OTLP endpoint, see "Connected" |
| 1     | First agent end-to-end (NL → investigate → finding) | A finding appears in the dashboard within 60s of failure injection |
| 2     | GitHub + Slack MCP integration | Slack message arrives with a specific commit SHA |
| 3     | Verification loop + multi-agent + per-agent memory | Agent auto-resolves the issue after a fix is deployed |
| 4     | Claude Code handoff | "Copy as Claude Code prompt" yields a runnable fix prompt |

See [`docs/PLAN.md`](docs/PLAN.md) for the full checklist and status log.

## Production architecture (one note)

The agent runtime is a long-running Python worker for demo simplicity. The
`run_one_step(snapshot_id) → next_snapshot_id` function is a pure step, with
no in-memory state between calls, so `services/agent-runtime/lambda_handler.py`
documents how to swap the worker for AWS Lambda + S3 event notifications —
which matches Firetiger's published architecture exactly. Same function,
different driver.

## Hosting

For the demo:

| Component                    | Host                     |
|------------------------------|--------------------------|
| Dashboard (Next.js)          | Vercel (free)            |
| OTLP receiver, control plane, agent runtime | Fly.io (free shared-cpu-1x) |
| Postgres + Auth + Realtime   | Supabase (free)          |
| Iceberg + snapshots storage  | AWS S3 free tier (5 GB)  |
| Monitored app                | Fork of [`opentelemetry-demo`](https://github.com/open-telemetry/opentelemetry-demo) running on laptop or DigitalOcean droplet |

## Documentation

- [`CLAUDE.md`](CLAUDE.md) — orientation for Claude Code sessions
- [`docs/PLAN.md`](docs/PLAN.md) — phased build plan and status log
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — three planes, data flow, hosting
- [`docs/AGENT_DESIGN.md`](docs/AGENT_DESIGN.md) — snapshot loop, worker, tools
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) — Postgres schema, Iceberg tables, S3 layout
- [`docs/UI_SPEC.md`](docs/UI_SPEC.md) — dashboard screens
- [`docs/DEMO.md`](docs/DEMO.md) — what success looks like
- [`docs/MONITORED_APP.md`](docs/MONITORED_APP.md) — Astronomy Shop fork setup
- [`docs/TECH_STACK.md`](docs/TECH_STACK.md) — stack choices with reasoning

## License

TBD.
