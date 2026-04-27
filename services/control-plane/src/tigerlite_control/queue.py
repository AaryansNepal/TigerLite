"""Postgres-backed job queue.

The schema is in `infra/migrations/0001_initial_schema.sql` (table `jobs`).
We use SELECT ... FOR UPDATE SKIP LOCKED for fan-out across workers, with a
visibility timeout via `locked_at`. A separate reaper unlocks stuck jobs.

Job kinds (reserved across all phases):
  - anomaly         : emitted by the anomaly watcher
  - cron            : emitted by APScheduler for scheduled agent runs
  - slack_message   : emitted by the Slack inbound webhook
  - snapshot_ready  : emitted after each snapshot write — drives the agent loop
  - verify_issue    : emitted to schedule a verification session
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import structlog

from .config import get_settings
from .db import get_pool

log = structlog.get_logger(__name__)


JOB_KINDS = {
    "anomaly",
    "cron",
    "slack_message",
    "snapshot_ready",
    "verify_issue",
}


async def enqueue(
    *,
    tenant_id: UUID | str,
    kind: str,
    payload: dict[str, Any],
    visible_at: str | None = None,
    max_attempts: int = 3,
) -> UUID:
    if kind not in JOB_KINDS:
        raise ValueError(f"unknown job kind: {kind!r}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO jobs (tenant_id, kind, payload, visible_at, max_attempts)
            VALUES ($1, $2, $3::jsonb, COALESCE($4::timestamptz, now()), $5)
            RETURNING id
            """,
            str(tenant_id),
            kind,
            _json_dumps(payload),
            visible_at,
            max_attempts,
        )
    log.debug("enqueued", kind=kind, tenant_id=str(tenant_id))
    return row["id"]


async def consume(consumer_id: str) -> dict[str, Any] | None:
    """Lock the next visible job for this consumer. Returns None if nothing
    is ready. Caller must call ack(job_id) on success or nack(job_id) on
    failure.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, kind, payload, attempts
                  FROM jobs
                 WHERE completed_at IS NULL
                   AND visible_at <= now()
                   AND consumer_id IS NULL
                 ORDER BY created_at
                 LIMIT 1
                 FOR UPDATE SKIP LOCKED
                """
            )
            if row is None:
                return None
            await conn.execute(
                """
                UPDATE jobs
                   SET consumer_id = $1,
                       locked_at = now(),
                       attempts = attempts + 1
                 WHERE id = $2
                """,
                consumer_id,
                row["id"],
            )
            return {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "kind": row["kind"],
                "payload": row["payload"],
                "attempts": row["attempts"] + 1,
            }


async def ack(job_id: UUID | str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE jobs SET completed_at = now() WHERE id = $1",
            job_id if isinstance(job_id, UUID) else UUID(str(job_id)),
        )


async def nack(job_id: UUID | str, error: str | None = None) -> None:
    """Release the lock so the job becomes visible again after the visibility
    timeout. If attempts >= max_attempts, mark completed with last_error so
    we stop retrying.
    """
    settings = get_settings()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            UPDATE jobs
               SET consumer_id = NULL,
                   locked_at = NULL,
                   visible_at = now() + interval '{settings.job_visibility_timeout_seconds} seconds',
                   last_error = $2,
                   completed_at = CASE WHEN attempts >= max_attempts THEN now() ELSE completed_at END
             WHERE id = $1
            """,
            job_id if isinstance(job_id, UUID) else UUID(str(job_id)),
            error,
        )


async def reap_stuck_jobs(timeout_seconds: int) -> int:
    """Releases jobs whose lock is older than timeout_seconds. Run on a cron.
    Returns the number of jobs released.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"""
            UPDATE jobs
               SET consumer_id = NULL,
                   locked_at = NULL,
                   visible_at = now()
             WHERE completed_at IS NULL
               AND consumer_id IS NOT NULL
               AND locked_at < now() - interval '{timeout_seconds} seconds'
            """
        )
        # asyncpg returns "UPDATE n" — parse the int.
        return int(result.split()[-1]) if result else 0


def _json_dumps(payload: dict[str, Any]) -> str:
    import json
    return json.dumps(payload, default=str)
