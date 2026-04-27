# Runbook

How to bring the system up locally and what to check.

## Pre-flight

1. **Rotate the Supabase credentials you pasted in chat earlier.**
   - Settings → Database → Reset database password.
   - Settings → API → Roll service_role key.
2. Generate a credential encryption key:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. Copy `.env.example` → `.env.local` at the repo root and fill in:
   - `SUPABASE_SERVICE_ROLE_KEY` (from step 1)
   - `DATABASE_URL` (from Supabase → Settings → Database → Connection string URI; tick "Use connection pooling")
   - `CREDENTIAL_ENCRYPTION_KEY` (from step 2)
   - `GEMINI_API_KEY` (https://aistudio.google.com/apikey — Phase 1+)
   Leave the rest as defaults for local dev.

## Bring up local infra

```bash
pnpm infra:up
# MinIO console:    http://localhost:9001  (minioadmin / minioadmin)
# Iceberg REST API: http://localhost:8181/v1/config
```

## Apply database schema

```bash
pnpm db:migrate
```

This runs every `.sql` file in `infra/migrations/` in lexical order against
your Supabase Postgres. Each migration is idempotent; re-running is safe.

If `psql` is not installed: paste the SQL files into Supabase's SQL editor
in order.

## Start services (3 terminals)

**Terminal A — control plane (Python/FastAPI)**
```bash
cd services/control-plane
uv sync
uv run uvicorn tigerlite_control.main:app --reload --port 8000
```

**Terminal B — agent runtime (Python worker)**
```bash
cd services/agent-runtime
uv sync
uv run python -m tigerlite_runtime.worker
```

**Terminal C — Go OTLP receiver**
```bash
cd services/ingest
go run ./cmd/ingest
```

## Start the dashboard

```bash
pnpm install
pnpm dev
# → http://localhost:3000
```

## End-to-end smoke test

1. Open http://localhost:3000, sign up with email/password.
2. Click **OpenTelemetry** card → Generate ingest token. Copy the token.
3. Send a single span with `otel-cli`:
   ```bash
   otel-cli span \
     --endpoint http://localhost:8080 \
     --protocol http/protobuf \
     --service checkout \
     --name "POST /api/checkout" \
     --otlp-headers "Authorization=Bearer <paste-token>"
   ```
4. The OpenTelemetry card flips to "Connected — receiving data from `checkout`".
5. (Phase 1+) Click **New agent**, type *"checkout flow should always be fast"*,
   answer the compiler's clarifying questions, watch the agent appear under
   `/agents`. Hit **Run now** → a session appears under the Sessions tab.
6. (Phase 2+) Connect GitHub + Slack via `/integrations` per the setup
   guides in `docs/SETUP_GITHUB_APP.md` and `docs/SETUP_SLACK_APP.md`.

## What to check when something breaks

| Symptom | Where to look |
|---------|---------------|
| OTLP `401 unauthorized` | `services/ingest` logs — wrong/expired bearer token |
| OTLP receives but Iceberg empty | `services/control-plane` logs around `iceberg_writer.py` |
| Anomaly watcher silent | `tick_anomaly` — check that the agent's scope_config has endpoints + the data has matching `http_route` |
| Agent stalls | Worker log — likely Gemini timeout. `AGENT_TOOL_TIMEOUT_SECONDS` in env |
| Slack post fails | `slack_connection.credentials_encrypted` exists? token valid? |
| MCP discovery returns nothing | `which github-mcp-server` / `which mcp-server-slack` — binaries installed? |
| Snapshot conflict | `If-None-Match: *` 412 means another worker raced you. Idempotent — next worker reads winner's state. |

## Production deploy (rough)

- Vercel: dashboard
- Fly.io: `services/ingest`, `services/control-plane`, `services/agent-runtime` (one VM, three processes)
- AWS S3: replace MinIO. Set `OBJECT_STORE=s3` and the AWS_* vars.
- Real domain: set `INGEST_URL` so the OTLP exporter has a stable URL.

The control plane and agent runtime are split into two `uv run` invocations
intentionally — they share Postgres + S3, no in-process coupling.
