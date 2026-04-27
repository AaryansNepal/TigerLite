"""Queue client mirroring the control plane's. We keep the SQL here so the
runtime doesn't depend on the control-plane Python package.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from .db import get_pool


async def consume(consumer_id: str) -> dict[str, Any] | None:
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
                   AND kind IN ('snapshot_ready', 'anomaly', 'cron', 'slack_message', 'verify_issue')
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
                   SET consumer_id = $1, locked_at = now(), attempts = attempts + 1
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


async def ack(job_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE jobs SET completed_at = now() WHERE id = $1", job_id)


async def nack(job_id: UUID, error: str | None = None) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE jobs
               SET consumer_id = NULL, locked_at = NULL,
                   visible_at = now() + interval '5 minutes',
                   last_error = $2,
                   completed_at = CASE WHEN attempts >= max_attempts THEN now() ELSE completed_at END
             WHERE id = $1
            """,
            job_id,
            error,
        )


async def enqueue_snapshot_ready(tenant_id: str, snapshot_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO jobs (tenant_id, kind, payload)
            VALUES ($1, 'snapshot_ready', $2::jsonb)
            """,
            UUID(tenant_id),
            json.dumps({"snapshot_id": snapshot_id}),
        )
