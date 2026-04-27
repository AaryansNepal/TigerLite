# services/ingest

OTLP/HTTP receiver for TigerLite v2.

## Endpoints

| Method | Path           | Auth | Purpose |
|--------|----------------|------|---------|
| GET    | `/health`      | none | Liveness check + version banner |
| GET    | `/metrics`     | none | (placeholder for now) |
| POST   | `/v1/traces`   | bearer | OTLP traces (protobuf or JSON) |
| POST   | `/v1/logs`     | bearer | OTLP logs |
| POST   | `/v1/metrics`  | bearer | OTLP metrics |

The bearer token is the per-tenant ingest token, validated against
`connections.ingest_token_hash` (bcrypt). On successful auth, decoded rows
are pushed into the in-memory batcher; the batcher flushes by size or
time and posts batches to the control plane's `/internal/iceberg/append`
endpoint, which uses PyIceberg to commit.

## Run locally

```bash
# In one terminal: bring up MinIO + Iceberg REST
pnpm infra:up

# In another: run the control plane (PyIceberg lives there)
cd services/control-plane && uv run uvicorn tigerlite_control.main:app --reload --port 8000

# In a third: run the receiver
cd services/ingest && go run ./cmd/ingest
```

## Smoke test (no real OTel SDK needed)

```bash
# 1. Insert a fake otel connection in Postgres (see docs/DATA_MODEL.md)
# 2. Generate a token in your shell; bcrypt-hash it; UPDATE the row.
# 3. Send a minimal OTLP/JSON payload:

curl -X POST http://localhost:8080/v1/traces \
  -H "Authorization: Bearer <your-test-token>" \
  -H "Content-Type: application/json" \
  -d @./testdata/minimal-traces.json
```
