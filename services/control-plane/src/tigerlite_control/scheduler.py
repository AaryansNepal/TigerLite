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
        asyncio.create_task(session_reaper_loop()),
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
            log.error("anomaly tick failed", err=repr(e))
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
            log.warning("agent scope eval failed", agent_id=str(a["id"]), err=repr(e))


async def evaluate_scope(tenant_id: str, scope_config: dict[str, Any]) -> dict[str, Any] | None:
    """Compute current state of the agent's scope. Returns evidence dict if
    anomalous, else None.

    Supports two metric types:
      - "latency_p95"  → p95 of duration_ms over the window vs threshold_ms
      - "error_rate"   → fraction of status_code='ERROR' spans vs threshold_percent
    Endpoints can match either http_route or service_name (so an agent
    declared with services=['payment'] still works).
    """
    if isinstance(scope_config, str):
        import json
        scope_config = json.loads(scope_config)
    metric = scope_config.get("metric", "latency_p95")
    endpoints = scope_config.get("endpoints", []) or scope_config.get("services", [])
    look_back_min = int(scope_config.get("look_back_minutes", 5))

    if not endpoints:
        return None

    # Endpoint filter: match http_route OR service_name OR span_name (catch-all
    # because the compiler sometimes lists service names like 'checkout' rather
    # than HTTP routes like '/api/checkout').
    eps = " OR ".join([
        f"http_route = '{_quote(e)}' OR service_name = '{_quote(e)}' OR span_name LIKE '%{_quote(e)}%'"
        for e in endpoints
    ])

    if metric == "error_rate":
        threshold_pct = float(scope_config.get("threshold_percent", 1.0))
        sql = f"""
            SELECT
              SUM(CASE WHEN status_code='ERROR' OR http_status_code >= 500 THEN 1 ELSE 0 END)::DOUBLE
                / GREATEST(COUNT(*), 1) * 100.0 AS error_pct,
              COUNT(*) AS n
            FROM traces
            WHERE start_time >= now() - INTERVAL '{look_back_min} minutes'
              AND ({eps})
        """
        try:
            result = run_tenant_query(tenant_id, sql)
        except Exception as e:
            log.debug("scope query failed", err=repr(e))
            return None
        if not result.rows or result.rows[0][1] == 0:
            return None
        error_pct = float(result.rows[0][0] or 0)
        if error_pct < threshold_pct:
            return None
        return {
            "metric": "error_rate",
            "endpoints": endpoints,
            "threshold_percent": threshold_pct,
            "current_error_pct": error_pct,
            "request_count": int(result.rows[0][1]),
            "window": f"last_{look_back_min}_minutes",
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

    # Default: latency_p95
    threshold_ms = float(scope_config.get("threshold_ms", 500))
    sql = f"""
        SELECT
          QUANTILE_CONT(duration_ms, 0.95) AS p95_now,
          AVG(duration_ms) AS avg_now,
          COUNT(*) AS n_now
        FROM traces
        WHERE start_time >= now() - INTERVAL '{look_back_min} minutes'
          AND ({eps})
    """
    try:
        result = run_tenant_query(tenant_id, sql)
    except Exception as e:
        log.debug("scope query failed (likely empty data)", err=repr(e))
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
            log.error("cron tick failed", err=repr(e))
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
            log.error("verification tick failed", err=repr(e))
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
            log.error("reaper failed", err=repr(e))
        await asyncio.sleep(interval_seconds)


async def session_reaper_loop() -> None:
    """Auto-fail sessions that have been stuck in 'running' with no progress
    for too long. Without this, transient runtime errors (Gemini 503, network
    blips) leave zombie sessions that show up in the dashboard with empty
    timelines, confusing the user.
    """
    log.info("session_reaper_loop starting")
    while True:
        try:
            n = await reap_stuck_sessions()
            if n:
                log.warning("reaped stuck sessions", count=n)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("session reaper failed", err=repr(e))
        await asyncio.sleep(60)


async def reap_stuck_sessions() -> int:
    """Mark sessions stuck >5 min in 'running' as failed. Two cases:
      - step_count = 0 and started_at < now() - 5min  → never made progress
      - latest_snapshot_id unchanged for >5min          → made progress then froze
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # No-progress sessions
        result = await conn.execute(
            """
            UPDATE sessions
               SET status = 'failed',
                   outcome = 'inconclusive',
                   ended_at = now(),
                   finding_summary = COALESCE(
                       finding_summary,
                       'Session stalled — runtime did not make progress within 5 minutes (likely upstream LLM error).'
                   )
             WHERE status = 'running'
               AND started_at < now() - interval '5 minutes'
               AND step_count = 0
            """
        )
        no_progress = int(result.split()[-1]) if result else 0

        # Progress-but-frozen sessions: latest_snapshot_id older than 5 min
        # (we approximate via ended_at being null + started_at + step_count*15s)
        result = await conn.execute(
            """
            UPDATE sessions
               SET status = 'timed_out',
                   outcome = 'inconclusive',
                   ended_at = now(),
                   finding_summary = COALESCE(
                       finding_summary,
                       'Session timed out — no snapshot progress for 5+ minutes.'
                   )
             WHERE status = 'running'
               AND step_count > 0
               AND started_at < now() - interval '15 minutes'
            """
        )
        frozen = int(result.split()[-1]) if result else 0

        # Clear current_issue_id for agents whose tracked issue lost its session
        await conn.execute(
            """
            UPDATE agents a
               SET current_issue_id = NULL
              FROM issues i
             WHERE a.current_issue_id = i.id
               AND i.status NOT IN ('open', 'verifying', 'regressed')
            """
        )

    return no_progress + frozen
