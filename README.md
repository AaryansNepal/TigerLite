# TigerLite — Agentic Observability

A miniature version of FireTiger's architecture: ingest telemetry into Apache Iceberg on MinIO, query with DuckDB, and run a Git-inspired snapshot-based agent that detects per-customer anomalies using OpenAI GPT-4o.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Simulator   │────▶│   Backend    │────▶│  MinIO (S3)      │
│  (10 custs)  │     │  (FastAPI)   │     │  ├── warehouse/  │
└─────────────┘     │              │     │  │   (Iceberg)   │
                    │  Ingestion   │     │  └── snapshots/  │
┌─────────────┐     │  Query (Duck)│     │      (Agent)     │
│  Dashboard   │◀──▶│  Agent       │     └──────────────────┘
│  (React)     │ SSE│  SSE         │
└─────────────┘     └──────┬───────┘     ┌──────────────────┐
                           │             │  REST Catalog     │
                           └────────────▶│  (Iceberg meta)  │
                                         └──────────────────┘
```

**5 Docker services:** MinIO → minio-setup → REST Catalog → Backend (FastAPI) → Simulator + Dashboard

## Key Design Decisions

- **REST Catalog** (`tabulario/iceberg-rest`) — shared Iceberg metadata across all containers
- **DuckDB + `iceberg_scan()`** — fast OLAP queries resolved via PyIceberg metadata paths
- **Snapshot-based agent** — Git-inspired immutable snapshots stored in MinIO, every reasoning step is auditable
- **Content-addressable object store** — agent messages stored by SHA-256 hash, deduplication built-in
- **SSE streaming** — real-time dashboard updates via Server-Sent Events
- **Single FastAPI backend** — ingestion + query + agent in one service for demo reliability

## Quick Start

### Prerequisites
- Docker & Docker Compose
- OpenAI API key (for the agent)

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

| URL | Description |
|-----|-------------|
| http://localhost:5173 | Dashboard |
| http://localhost:8000 | Backend API |
| http://localhost:9001 | MinIO Console (admin/password) |

### API

```bash
# Health check
curl localhost:8000/health

# Customer health metrics
curl localhost:8000/api/customer-health

# Recent telemetry
curl localhost:8000/api/telemetry/recent

# Agent findings
curl localhost:8000/api/findings

# Trigger bad deploy manually
curl -X POST localhost:8000/api/scenario/trigger-bad-deploy

# Trigger agent investigation
curl -X POST localhost:8000/api/agent/run

# SSE stream
curl localhost:8000/api/agent/stream
```

## Demo Flow (3-5 minutes)

1. `docker compose up` — all services start
2. Dashboard shows live telemetry, all 10 customers green
3. After 60s (or click "Trigger Bad Deploy"), Wonka Industries degrades
4. Customer health table: Wonka row turns red with p99 > 2000ms
5. Agent detects per-customer anomaly, investigates with DuckDB queries
6. Finding appears: "Latency regression for Wonka Industries after deploy v1.2.4"
7. Click snapshot timeline to see every step of agent reasoning — immutable and auditable

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
├── simulator/
│   ├── src/
│   │   ├── scenarios.py       # Traffic generation
│   │   └── main.py            # Simulator loop
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
├── docker-compose.yml
├── scripts/demo.sh
└── README.md
```
