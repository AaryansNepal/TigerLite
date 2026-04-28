"""Sessions API: list per-agent sessions, fetch session detail with snapshot
chain rendered as objects.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, Response, status

from ..auth import CurrentUser
from ..db import get_pool, with_retry
from ..models import Session
from ..object_store import make_object_store

router = APIRouter()
log = structlog.get_logger(__name__)


# Cache for the timeline endpoint. Snapshots are immutable (content-addressed),
# so we can safely cache by latest_snapshot_id forever. Reset on process
# restart. Keeps the second visit to a session page instant.
_timeline_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_TIMELINE_CACHE_TTL = 600  # seconds — long because content-addressed


@router.get("", response_model=list[Session])
async def list_sessions(
    ctx: CurrentUser,
    agent_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> list[Session]:
    async def _query() -> list[Any]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            if agent_id:
                return await conn.fetch(
                    """
                    SELECT * FROM sessions
                     WHERE tenant_id = $1 AND agent_id = $2
                     ORDER BY started_at DESC
                     LIMIT $3
                    """,
                    UUID(ctx.tenant_id),
                    agent_id,
                    limit,
                )
            return await conn.fetch(
                """
                SELECT * FROM sessions
                 WHERE tenant_id = $1
                 ORDER BY started_at DESC
                 LIMIT $2
                """,
                UUID(ctx.tenant_id),
                limit,
            )

    rows = await with_retry(_query)
    return [_row_to_session(r) for r in rows]


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: UUID, ctx: CurrentUser) -> Session:
    async def _query() -> Any:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM sessions WHERE id = $1 AND tenant_id = $2",
                session_id,
                UUID(ctx.tenant_id),
            )

    row = await with_retry(_query)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _row_to_session(row)


@router.get("/{session_id}/timeline")
async def session_timeline(
    session_id: UUID, ctx: CurrentUser, response: Response
) -> dict[str, Any]:
    """Return the latest snapshot's objects, in order, for rendering the
    session timeline cards.

    Performance:
      - Object fetches from MinIO are parallelised (asyncio.gather) instead
        of serial. ~12 objects went from ~180ms → ~20ms.
      - Cached by latest_snapshot_id since snapshots are immutable. Second
        visit to a session page is essentially free.
      - Postgres reads wrapped in retry to absorb Supabase pooler blips.
    """
    sess = await get_session(session_id, ctx)
    if sess.latest_snapshot_id is None:
        return {"snapshot_id": sess.root_snapshot_id, "objects": []}

    cache_key = sess.latest_snapshot_id
    cached = _timeline_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < _TIMELINE_CACHE_TTL:
        response.headers["X-Cache"] = "HIT"
        return cached[1]

    obj_store = make_object_store()
    manifest_bytes = await obj_store.get(sess.latest_snapshot_id)
    manifest = json.loads(manifest_bytes)
    hashes = manifest.get("object_hashes", [])

    # Parallel fetch — was the slowest part of the path before this.
    async def _fetch_object(h: str) -> dict[str, Any] | None:
        try:
            blob = await obj_store.get(f"objects/{h[:2]}/{h}")
            return json.loads(blob)
        except Exception as e:
            log.warning("missing object", hash=h, err=str(e))
            return None

    raw = await asyncio.gather(*[_fetch_object(h) for h in hashes])
    objects = [o for o in raw if o is not None]

    payload = {
        "snapshot_id": sess.latest_snapshot_id,
        "objects": objects,
        "manifest": manifest,
    }
    _timeline_cache[cache_key] = (time.time(), payload)
    response.headers["X-Cache"] = "MISS"
    return payload


def _row_to_session(row: Any) -> Session:
    d = dict(row)
    if isinstance(d.get("trigger_payload"), str):
        d["trigger_payload"] = json.loads(d["trigger_payload"])
    return Session.model_validate(d)
