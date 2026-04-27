# The monitored app — OpenTelemetry Demo (Astronomy Shop)

This is the application TigerLite watches during the demo. We don't build it; we fork the canonical OpenTelemetry community demo and configure it to send telemetry to TigerLite's OTLP endpoint instead of (or in addition to) its bundled backends.

## Why this app

[`open-telemetry/opentelemetry-demo`](https://github.com/open-telemetry/opentelemetry-demo) — the "Astronomy Shop" — is the canonical OTel demo. It's a microservice-based e-commerce app with services for Frontend, Cart, Checkout, Payment, Shipping, Product Catalog, Recommendation, Email, Ad, Currency, Fraud Detection, Accounting, plus Kafka/Postgres/Redis behind the scenes. Every service is instrumented with the official OpenTelemetry SDKs in its native language.

The killer feature for our demo: it ships with **[`flagd`](https://flagd.dev) feature flags that inject failures**. We can flip flags like:

- `paymentServiceFailure` — make Payment throw 500s on a percentage of calls
- `cartFailure` — make Cart return broken responses
- `recommendationServiceCacheFailure` — cause cache misses, cascading latency
- `imageSlowLoad` — slow image loading on the frontend
- `productCatalogFailure` — catalog 500s

This means our demo regression isn't engineered — it's a checkbox.

## Setup

### Fork

1. Aaryan forks `open-telemetry/opentelemetry-demo` to his GitHub account: `AaryansNepal/opentelemetry-demo` (or similar).
2. Clone locally for editing.

### Point telemetry at TigerLite

Edit `src/otelcollector/otelcol-config.yml`. Find the `exporters` section and add the TigerLite OTLP endpoint:

```yaml
exporters:
  # Existing exporters (OTLP/HTTP to bundled Jaeger, Prometheus, etc.) — keep them
  # so the bundled UI still works for cross-checking.

  otlphttp/tigerlite:
    endpoint: "https://api.tigerlite.dev"     # or http://host.docker.internal:8080 for local dev
    headers:
      Authorization: "Bearer ${TIGERLITE_INGEST_TOKEN}"
    tls:
      insecure: false  # set true for local dev with self-signed certs

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlphttp/tigerlite, otlp/jaeger]   # add tigerlite alongside existing
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlphttp/tigerlite, opensearch]
    metrics:
      receivers: [otlp, prometheus]
      processors: [batch]
      exporters: [otlphttp/tigerlite, prometheus]
```

The `${TIGERLITE_INGEST_TOKEN}` is read from the environment. Set it via `.env` at the repo root:

```bash
TIGERLITE_INGEST_TOKEN=<paste from TigerLite Telemetry connect modal>
```

Reference it in `docker-compose.yml` for the otelcollector service:

```yaml
otelcol:
  environment:
    - TIGERLITE_INGEST_TOKEN
```

Commit this change to the fork. The repo now has a "configured for TigerLite" version, with the Slack demo target as the audience.

### Run

```bash
docker compose up -d
```

Wait ~30 seconds. The Astronomy Shop frontend is at `http://localhost:8080`. Telemetry is now flowing to:

- The bundled stack (Jaeger at :16686, Grafana at :3000, etc.) — for cross-checking
- TigerLite's OTLP endpoint — for the agent to consume

In TigerLite's dashboard, the Telemetry connect modal flips to "Connected — receiving data from frontend, cart, checkout, payment, shipping, recommendation, ..."

### Resource requirements

The full stack uses ~6-8GB of RAM. If running on a laptop with 16GB total, close other heavy apps before the demo.

To slim down for resource-constrained machines, comment out non-essential services in `docker-compose.yml`:

- `accounting` — not part of the demo flow
- `frauddetection` — not part of the demo flow
- `email` — not part of the demo flow
- `currency` — frontend can fall back without it
- `ad` — purely visual, can be disabled

Keep: `frontend`, `frontendproxy`, `cart`, `checkout`, `payment`, `productcatalog`, `recommendation`, `shipping`, `quote`, `loadgenerator`, `flagd`, `kafka`, `postgres`, `valkey-cart`, `otelcol`.

This brings memory to ~4GB and is sufficient for the demo.

## The demo manipulation

### Trigger a regression mid-presentation

Open the flagd UI:

```
http://localhost:8080/feature
```

Toggle `paymentServiceFailure` to `on`. The `loadgenerator` service is constantly hitting `/cart`, `/checkout`, and `/payment`, so within 30-60 seconds you'll have noticeable error and latency telemetry flowing. TigerLite's anomaly watcher detects deviation, triggers an investigation, and the agent posts to Slack.

### Reset

Toggle the flag back `off`. Within 5 minutes, the verification session confirms recovery.

### Optional: stage a more elaborate demo

For a more impressive narrative, instead of just toggling a flag mid-presentation:

1. Before the presentation, write an actual code change to `src/payment/main.go` (or whichever service you're using) that introduces a real bug — e.g. an unindexed query, an N+1 loop, a synchronous call where async was needed.
2. Commit and push to a branch on your fork.
3. Open a PR titled something like "feat: switch to new currency provider" — the agent's correlation will land on this commit's title.
4. Merge the PR mid-demo (or have it merged shortly before).
5. Now the agent's investigation can identify *real* code in the diff, not just "the flag is on."

This is more impressive because the agent reads the actual changed lines and reasons about them. Trade-off: more setup time, more risk of something not working live.

## Hosting the monitored app

Three options, in increasing order of "live-ness":

### Option A: laptop only (recommended for first demo)

Run on Aaryan's laptop during the presentation. `docker compose up`. The OTLP exporter sends to TigerLite's hosted endpoint. Audience sees the Astronomy Shop UI by Aaryan switching browser tabs.

Pros: zero hosting cost, no remote ops to manage, telemetry includes Aaryan's laptop's network conditions which is fine for demo.

Cons: requires a working laptop in the room, and the audience can't poke at it themselves.

### Option B: small VPS (intermediate)

DigitalOcean droplet, AWS Lightsail, or Hetzner CX21. ~$6-10/month. Run docker-compose on the VPS. Map the frontend port to a public IP. Audience can access the storefront URL.

Setup:

```bash
# On a fresh Ubuntu 22.04 VPS with 4GB+ RAM
curl -fsSL https://get.docker.com | sh
git clone https://github.com/AaryansNepal/opentelemetry-demo
cd opentelemetry-demo
echo "TIGERLITE_INGEST_TOKEN=..." > .env
docker compose up -d

# Set up nginx reverse proxy for the frontend, with letsencrypt cert
# (or just expose port 8080 directly for demo simplicity)
```

Pros: live URL, audience can interact, more impressive.

Cons: ongoing cost, real-world hosting complexity.

### Option C: AWS free tier (advanced)

`t3.medium` is within free tier (750 hours/month for first 12 months), 4GB RAM. Same setup as Option B. Free for the demo period.

## Verifying the connection

Quick sanity check after configuring the fork:

```bash
# In one terminal: tail the otelcollector logs
docker compose logs -f otelcol

# In another: hit a frontend endpoint manually
curl -s http://localhost:8080/api/cart -H "Cookie: ..."
```

Within seconds, you should see otelcollector log lines indicating it's exporting to the TigerLite endpoint. If you see `Permanent error: Unauthorized`, the ingest token is wrong. If you see `connection refused`, the endpoint URL is wrong.

In the TigerLite dashboard, the Telemetry connect modal should flip to Connected within 30 seconds of the first event reaching the OTLP receiver.

## What we're not building

- **A storefront from scratch.** Don't. The user said *explicitly* they don't want to waste time on this. The OpenTelemetry Demo provides everything we need.
- **Custom OTel instrumentation.** All instrumentation is already in place from the demo. Nothing to add.
- **A separate "monitored app" repo in the TigerLite codebase.** The Astronomy Shop fork lives in its own repo, not inside ours. Reference it from `docs/MONITORED_APP.md` (this file). The TigerLite repo just consumes the OTLP traffic it produces.
