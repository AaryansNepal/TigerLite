"""TigerLite v2 control plane.

Responsibilities:
  - Agents CRUD (consumed by the dashboard).
  - Internal Iceberg writer (called by the Go ingest service for each batch).
  - Job queue (Postgres SELECT FOR UPDATE SKIP LOCKED).
  - Anomaly watcher (per-minute tick over active agents).
  - Cron scheduler (hourly checks, verification cadence).
  - Trigger router (decides new-or-resume-session, writes initial snapshot).
  - Slack inbound webhook.
  - Connection management (token issue, GitHub/Slack OAuth callbacks).

Heavy logic lives here so the dashboard's Next.js API routes stay thin.
"""

__version__ = "2.0.0.dev0"
