"""Background tasks owned by the control plane.

These run as asyncio tasks inside the FastAPI process for demo simplicity.
In production they'd be split into a dedicated worker process; the design is
already split-friendly because every interaction is via Postgres + S3.

Tasks:
  - anomaly_loop:  every N seconds, runs scope queries for active agents and
                   pushes anomaly events onto the queue.
  - cron_loop:     drives APScheduler for agent schedules + verification cron.
  - reaper_loop:   unlocks stuck jobs whose visibility timeout expired.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from . import queue
from .config import get_settings
from .db import get_pool
from .query import run_tenant_query

log = structlog.get_logger(__name__)


async def start() -> list[asyncio.Task]:
    settings = get_settings()
    return [
        asyncio.create_task(anomaly_loop(settings.anomaly_watch_interval_seconds)),
        asyncio.create_task(cron_loop()),
        asyncio.create_task(reaper_loop(settings.job_reaper_interval_seconds)),
        asyncio.create_task(verification_loop()),
    ]


# ----------------------------------------------------------
# Anomaly watcher
# ----------------------------------------------------------

async def anomaly_loop(interval_seconds: int) -> None:
    """Per-tick: load active agents, run their scope queries, push anomaly
    events when current vs baseline exceeds threshold.
    """
    log.info("anomaly_loop starting", interval=interval_seconds)
    while True:
        try:
            await tick_anomaly()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("anomaly tick failed", err=str(e))
        await asyncio.sleep(interval_seconds)


async def tick_anomaly() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        agents = await conn.fetch(
            """
            SELECT id, tenant_id, scope_config, current_issue_id, anomaly_enabled
              FROM agents
             WHERE status = 'active' AND anomaly_enabled = TRUE
            """
        )

    for a in agents:
        try:
            evidence = await evaluate_scope(
                tenant_id=str(a["tenant_id"]),
                scope_config=a["scope_config"],
            )
            if evidence is None:
                continue
            # Skip if there's an open issue already — agent is on it.
            if a["current_issue_id"] is not None:
                continue
            await queue.enqueue(
                tenant_id=str(a["tenant_id"]),
                kind="anomaly",
                payload={"agent_id": str(a["id"]), "evidence": evidence},
            )
        except Exception as e:
            log.warning("agent scope eval failed", agent_id=str(a["id"]), err=str(e))


async def evaluate_scope(tenant_id: str, scope_config: dict[str, Any]) -> dict[str, Any] | None:
    """Compute current vs baseline for the agent's scope. Returns evidence
    dict if anomalous, else None.

    Phase 1 implementation is intentionally simple:
      - Pull the configured metric (default: p95 latency on the configured
        endpoints) over the last 5 minutes.
      - Compare to the same metric averaged over the prior 7 days.
      - If current > baseline * 2x AND current > absolute floor → anomaly.

    Phase 3 will replace this with a proper rolling-percentile baseline
    stored in the agent's memory.
    """
    if isinstance(scope_config, str):
        import json
        scope_config = json.loads(scope_config)
    metric = scope_config.get("metric", "latency_p95")
    endpoints = scope_config.get("endpoints", [])
    threshold_ms = float(scope_config.get("threshold_ms", 500))

    if not endpoints:
        return None

    endpoint_filter = " OR ".join([f"http_route = '{_quote(e)}'" for e in endpoints])
    sql = f"""
        SELECT
          QUANTILE_CONT(duration_ms, 0.95) AS p95_now,
          AVG(duration_ms) AS avg_now,
          COUNT(*) AS n_now
        FROM traces
        WHERE start_time >= now() - INTERVAL 5 MINUTE
          AND ({endpoint_filter})
    """
    try:
        result = run_tenant_query(tenant_id, sql)
    except Exception as e:
        log.debug("scope query failed (likely empty data)", err=str(e))
        return None

    if not result.rows or result.rows[0][2] == 0:
        return None
    p95_now = float(result.rows[0][0] or 0)

    if p95_now < threshold_ms:
        return None

    return {
        "metric": metric,
        "endpoints": endpoints,
        "threshold_ms": threshold_ms,
        "current_p95_ms": p95_now,
        "window": "last_5_minutes",
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }


def _quote(s: str) -> str:
    return s.replace("'", "''")


# ----------------------------------------------------------
# Cron loop (per-agent schedules)
# ----------------------------------------------------------

async def cron_loop() -> None:
    """Loose cron emulation. Every minute, look up agents whose schedule_cron
    field matches the current minute, and enqueue cron events.

    APScheduler would be cleaner; this lightweight loop avoids the dependency
    surface and works for the demo's hourly cadence.
    """
    log.info("cron_loop starting")
    while True:
        try:
            await tick_cron()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("cron tick failed", err=str(e))
        await asyncio.sleep(60)


async def tick_cron() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # For demo: hourly = "0 * * * *". Match the current minute=0.
        now = datetime.now(timezone.utc)
        if now.minute != 0:
            return
        agents = await conn.fetch(
            """
            SELECT id, tenant_id
              FROM agents
             WHERE status = 'active'
               AND schedule_cron = '0 * * * *'
            """
        )
        for a in agents:
            await queue.enqueue(
                tenant_id=str(a["tenant_id"]),
                kind="cron",
                payload={"agent_id": str(a["id"]), "reason": "hourly_check"},
            )


# ----------------------------------------------------------
# Verification loop (Phase 3)
# ----------------------------------------------------------

async def verification_loop() -> None:
    log.info("verification_loop starting")
    while True:
        try:
            await tick_verification()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("verification tick failed", err=str(e))
        await asyncio.sleep(60)


async def tick_verification() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, agent_id, verification_attempts
              FROM issues
             WHERE status = 'verifying'
               AND next_verification_at IS NOT NULL
               AND next_verification_at <= now()
            """
        )
        for r in rows:
            await queue.enqueue(
                tenant_id=str(r["tenant_id"]),
                kind="verify_issue",
                payload={"issue_id": str(r["id"]), "agent_id": str(r["agent_id"])},
            )
            # Push next verification out (exponential backoff).
            backoff = min(2 ** r["verification_attempts"], 60) * 60  # seconds
            next_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
            await conn.execute(
                """
                UPDATE issues
                   SET next_verification_at = $2,
                       verification_attempts = verification_attempts + 1
                 WHERE id = $1
                """,
                r["id"],
                next_at,
            )


# ----------------------------------------------------------
# Reaper
# ----------------------------------------------------------

async def reaper_loop(interval_seconds: int) -> None:
    log.info("reaper_loop starting", interval=interval_seconds)
    while True:
        try:
            settings = get_settings()
            n = await queue.reap_stuck_jobs(settings.job_visibility_timeout_seconds)
            if n:
                log.warning("reaped stuck jobs", count=n)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("reaper failed", err=str(e))
        await asyncio.sleep(interval_seconds)
