# TigerLite — Agentic Observability

A miniature version of FireTiger's architecture: ingest telemetry through a Go microservice into Apache Iceberg on MinIO, query with DuckDB, run a Git-inspired snapshot-based agent that detects per-customer anomalies, and expose the data lake via MCP tools for Claude Desktop.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Simulator   │────▶│ Go Ingestion │────▶│   Backend    │────▶│  MinIO (S3)      │
│  (10 custs)  │     │ (batch+fwd)  │     │  (FastAPI)   │     │  ├── warehouse/  │
└─────────────┘     └──────────────┘     │              │     │  │   (Iceberg)   │
                                         │  Ingestion   │     │  └── snapshots/  │
┌─────────────┐                          │  Query (Duck)│     │      (Agent)     │
│  Dashboard   │◀──────────────────────▶│  Agent       │     └──────────────────┘
│  (React)     │ SSE                     │  SSE         │
└─────────────┘                          └──────┬───────┘     ┌──────────────────┐
                                                │             │  REST Catalog     │
┌─────────────┐                                 └────────────▶│  (Iceberg meta)  │
│  MCP Server  │────── DuckDB + iceberg_scan() ──────────────▶│                  │
│  (Claude)    │                                              └──────────────────┘
└─────────────┘
```

**7 Docker services:** MinIO → minio-setup → REST Catalog → Backend (FastAPI) → Go Ingestion → Simulator + Dashboard
**MCP Server** runs locally via Claude Desktop (stdio transport, `profiles: [mcp]`)

## What This Demonstrates

- **Apache Iceberg** — table format with REST catalog, not just Parquet files
- **DuckDB + `iceberg_scan()`** — fast OLAP queries resolved via PyIceberg metadata paths
- **Git-inspired agent snapshots** — immutable, content-addressable reasoning chains stored in MinIO
- **Go microservice** — channel-based batching, stdlib-only HTTP, multi-stage Docker build
- **MCP tool server** — Claude Desktop can query the data lake directly (3 tools at different abstraction levels)
- **SSE streaming** — real-time dashboard updates via Server-Sent Events

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Gemini API key (for the agent)

### Run

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env and set your OPENAI_API_KEY

# 2. Start everything
./scripts/demo.sh

# Or manually:
docker compose up --build
```

### Endpoints

| URL | Service | Description |
|-----|---------|-------------|
| http://localhost:5173 | Dashboard | React UI with live charts |
| http://localhost:8000 | Backend API | FastAPI — ingestion, query, agent |
| http://localhost:8080 | Go Ingestion | High-throughput event intake |
| http://localhost:9001 | MinIO Console | Object storage UI (admin/password) |

## Design Decisions

- **REST Catalog** (`tabulario/iceberg-rest`) — I chose a shared Iceberg metadata catalog so every service sees the same table state. This mirrors how production Iceberg deployments work with Nessie or AWS Glue.

- **DuckDB + `iceberg_scan()`** — instead of running a Spark cluster, DuckDB reads Iceberg metadata directly. This keeps the demo lightweight while still using real Iceberg table format with snapshots and schema evolution.

- **Snapshot-based agent** — every agent reasoning step is stored as an immutable, content-addressable object in MinIO (SHA-256 keyed). This is inspired by Git's object model and makes every investigation fully auditable.

- **Go ingestion service** — I built a separate ingestion layer in Go to demonstrate familiarity with the language. It uses stdlib-only HTTP, channel-based batching with select+ticker, and atomic counters — no frameworks needed. The ~15MB multi-stage Docker image shows I understand production container practices.

- **MCP tool server** — FireTiger uses MCP as their extensibility mechanism, so I built a tool server that lets Claude Desktop query the data lake directly. Three tools at different abstraction levels: raw SQL, pre-built health metrics, and deploy timeline.

## Project Structure

```
FireTiger/
├── backend/
│   ├── src/
│   │   ├── main.py            # FastAPI app, routes, lifecycle
│   │   ├── config.py          # Environment configuration
│   │   ├── schema.py          # Pydantic models
│   │   ├── iceberg_writer.py  # PyIceberg catalog + write
│   │   ├── ingestion.py       # Event buffer + flush
│   │   ├── query.py           # DuckDB queries via iceberg_scan
│   │   ├── events.py          # SSE event bus
│   │   └── agent/
│   │       ├── object_store.py  # Content-addressable store
│   │       ├── snapshot.py      # Immutable snapshot engine
│   │       ├── tools.py         # Agent tool definitions
│   │       ├── prompts.py       # System prompt
│   │       └── runtime.py       # Agent execution loop
│   ├── Dockerfile
│   └── pyproject.toml
├── go-ingestion/
│   ├── main.go                # Entry point: env config, wire batcher, start server
│   ├── handler.go             # HTTP handlers: /ingest, /health, /metrics
│   ├── detector.go            # Sliding-window anomaly detector, auto-triggers agent
│   ├── batcher.go             # Channel-based batching goroutine
│   ├── Dockerfile             # Multi-stage build (~15MB image)
│   └── go.mod
├── mcp-server/
│   ├── server.py              # MCP server entry point (stdio transport)
│   ├── tools.py               # 3 tools: query_events, customer_health, deploy_history
│   ├── claude_desktop_config.json  # Example Claude Desktop config
│   ├── Dockerfile
│   └── pyproject.toml
├── simulator/
│   ├── src/
│   │   ├── scenarios.py       # Traffic generation
│   │   └── main.py            # Simulator loop (routes via Go service)
│   ├── Dockerfile
│   └── pyproject.toml
├── dashboard/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── lib/api.js
│   │   ├── hooks/{usePolling,useSSE}.js
│   │   └── components/
│   │       ├── StatusBar.jsx
│   │       ├── CustomerHealthTable.jsx
│   │       ├── LatencyChart.jsx
│   │       ├── AgentFindingsList.jsx
│   │       ├── SnapshotTimeline.jsx
│   │       └── LiveEventFeed.jsx
│   ├── Dockerfile
│   └── nginx.conf
├── scripts/demo.sh
├── docker-compose.yml
└── README.md
```

## Work Flow

1. `docker compose up` — all services start, Go ingestion accepts traffic on :8080
2. Dashboard shows live telemetry, all 10 customers green
3. After 60s (or click "Trigger Bad Deploy"), Wonka Industries degrades
4. Customer health table: Wonka row turns red with p99 > 2000ms
5. Agent detects per-customer anomaly, investigates with DuckDB queries
6. Finding appears: "Latency regression for Wonka Industries after deploy v1.2.4"
7. Click snapshot timeline to see every step of agent reasoning — immutable and auditable

## Go Ingestion Service

The Go service sits between the simulator and the Python backend, accepting events on `:8080` and forwarding them in batches.

**Key implementation details:**
- **Channel + select + ticker** for batching (flush on 50 events or every 2s)
- **`sync/atomic` counters** for lock-free metrics
- **`*string` for `ErrorMessage`** to handle JSON null (matches Python's `Optional[str]`)
- **Non-blocking submit** with backpressure logging when the channel is full
- **Multi-stage Docker build** — final image is ~15MB on Alpine

```bash
# Test the Go service directly
curl localhost:8080/health
curl localhost:8080/metrics
curl -X POST localhost:8080/ingest \
  -H "Content-Type: application/json" \
  -d '{"timestamp":"2025-01-01T00:00:00Z","trace_id":"abc-123","customer_id":"c1","customer_name":"Acme","endpoint":"/api/data","method":"GET","status_code":200,"latency_ms":42.5,"deploy_version":"v1.0","region":"us-east-1"}'
```

## MCP Tool Server

The MCP server exposes TigerLite's Iceberg data lake to Claude Desktop (or any MCP-compatible client) via three tools at different abstraction levels:

| Tool | Description | Abstraction |
|------|-------------|-------------|
| `query_events` | Run arbitrary SQL against the events table | Raw — full flexibility |
| `get_customer_health` | P50/P99 latency, error rates, per customer | Pre-built — common query |
| `get_deploy_history` | Deploy version timeline with impact metrics | Domain-specific |

**Connect Claude Desktop:**

1. Start TigerLite: `docker compose up --build -d`
2. Copy `mcp-server/claude_desktop_config.json` into your Claude Desktop MCP settings
3. Ask Claude: "Which customer has the highest P99 latency right now?"

## API Reference

### Go Ingestion (`:8080`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/ingest` | Accept a telemetry event |
| GET | `/health` | Liveness check |
| GET | `/metrics` | Throughput counters |

### Backend (`:8000`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Liveness check |
| POST | `/ingest` | Direct event ingestion |
| GET | `/api/customer-health` | Per-customer metrics |
| GET | `/api/telemetry/recent` | Recent events |
| GET | `/api/findings` | Agent findings |
| POST | `/api/scenario/trigger-bad-deploy` | Trigger bad deploy |
| POST | `/api/agent/run` | Trigger agent investigation |
| GET | `/api/agent/stream` | SSE event stream |

## What I'd Add Next

**Claude Code integration** — agent finds the bug, generates a PR to fix it, closes the detect→fix loop

**Long-horizon agents** — continuous monitoring with persistent memory across sessions, not single investigation cycles

**Agent branching** — parallel investigation paths that fork from a snapshot, explore different hypotheses, merge results

**Customer knowledge graph** — agents learn per-customer baselines over days/weeks, detect subtle drift that thresholds miss
